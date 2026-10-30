import json  
import math  
import threading  
import time  
from collections import deque  
from concurrent.futures import ThreadPoolExecutor  
from pathlib import Path  
  
import rclpy  
from geometry_msgs.msg import TwistStamped  
from openai import OpenAI  
from rclpy.node import Node  
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy  
  
  
# 接続設定  
LLM_BASE_URL = "http://x.x.x.x:1234/v1"  
LLM_MODEL = "local-model"  
  
# 動作の制限値  
MAX_LINEAR_SPEED = 0.3       # m/s  
MAX_ANGULAR_SPEED = 1.0      # rad/s  
MIN_DURATION_SEC = 0.1  
MAX_DURATION_SEC = 30.0      # 1動作の最大時間  
MAX_COMMANDS = 10  
MAX_TOTAL_DURATION_SEC = 120.0  
  
# ROS速度指令の送信周期  
PUBLISH_PERIOD_SEC = 0.1  
  
# API・モデルが対応している場合に True へ変更できます。  
# 未対応の場合はFalseのまま使用してください。  
USE_JSON_RESPONSE_FORMAT = False  
  
  
class NaturalLanguageController(Node):  
    def __init__(self):  
        super().__init__("natural_language_controller")  
  
        qos_profile = QoSProfile(  
            history=HistoryPolicy.KEEP_LAST,  
            depth=10,  
            reliability=ReliabilityPolicy.RELIABLE,  
        )  
  
        self.publisher = self.create_publisher(  
            TwistStamped,  
            "/cmd_vel",  
            qos_profile,  
        )  
  
        self.lock = threading.Lock()  
  
        self.linear_x = 0.0  
        self.angular_z = 0.0  
        self.deadline = 0.0  
  
        # 未実行の動作  
        self.command_queue = deque()  
  
        # 現在の動作番号と全動作数  
        self.command_index = 0  
        self.command_count = 0  
        self.active_command = False  
  
        # 古いLLM応答を無効化するためのID  
        self.request_id = 0  
        self.closed = False  
  
        self.timer = self.create_timer(  
            PUBLISH_PERIOD_SEC,  
            self.publish_velocity,  
        )  
  
    def _publish_locked(self, linear_x, angular_z):  
        """self.lockを取得した状態で呼び出す。"""  
        msg = TwistStamped()  
        msg.header.stamp = self.get_clock().now().to_msg()  
        msg.header.frame_id = "base_link"  
        msg.twist.linear.x = linear_x  
        msg.twist.angular.z = angular_z  
        self.publisher.publish(msg)  
  
    def _clear_sequence_locked(self):  
        """動作列と現在の速度を消去する。"""  
        self.command_queue.clear()  
        self.linear_x = 0.0  
        self.angular_z = 0.0  
        self.deadline = 0.0  
        self.command_index = 0  
        self.command_count = 0  
        self.active_command = False  
  
    def begin_request(self):  
        """  
        新しい入力を開始する。  
  
        現在の速度を取得した後、実行中の動作列を停止する。  
        LLM応答の待機中は停止状態を維持する。  
        """  
        with self.lock:  
            if self.closed:  
                raise RuntimeError("コントローラーは終了しています")  
  
            now = time.monotonic()  
  
            if self.active_command and now < self.deadline:  
                current_velocity = {  
                    "linear_x": self.linear_x,  
                    "angular_z": self.angular_z,  
                }  
            else:  
                current_velocity = {  
                    "linear_x": 0.0,  
                    "angular_z": 0.0,  
                }  
  
            self.request_id += 1  
  
            self._clear_sequence_locked()  
            self._publish_locked(0.0, 0.0)  
  
            return self.request_id, current_velocity  
  
    def apply_commands(self, request_id, commands):  
        """検証済みの動作列を登録する。"""  
        with self.lock:  
            # 新しい入力や停止後に届いた古い応答は無視する。  
            if self.closed or request_id != self.request_id:  
                return False  
  
            self._clear_sequence_locked()  
  
            self.command_queue.extend(commands)  
            self.command_count = len(commands)  
  
            # 実行開始はROSタイマーが行う。  
            return True  
  
    def fail_request(self, request_id):  
        """現在の入力に対応する失敗の場合だけ停止する。"""  
        with self.lock:  
            if self.closed or request_id != self.request_id:  
                return False  
  
            self.request_id += 1  
            self._clear_sequence_locked()  
            self._publish_locked(0.0, 0.0)  
            return True  
  
    def stop(self):  
        """現在の動作・残りの動作・処理中のLLM応答を無効化する。"""  
        with self.lock:  
            self.request_id += 1  
            self._clear_sequence_locked()  
            self._publish_locked(0.0, 0.0)  
  
    def close(self):  
        """終了時に停止し、以降のLLM応答を無効化する。"""  
        with self.lock:  
            self.closed = True  
            self.request_id += 1  
            self._clear_sequence_locked()  
  
            if rclpy.ok():  
                self._publish_locked(0.0, 0.0)  
  
    def publish_velocity(self):  
        """ROSタイマーから呼び出し、動作を順次実行する。"""  
        with self.lock:  
            if self.closed:  
                return  
  
            now = time.monotonic()  
  
            # 現在の動作の終了判定  
            if self.active_command and now >= self.deadline:  
                self.get_logger().info(  
                    f"動作 {self.command_index}/{self.command_count} 完了"  
                )  
  
                self.linear_x = 0.0  
                self.angular_z = 0.0  
                self.deadline = 0.0  
                self.active_command = False  
  
                # 動作境界で停止指令を送る。  
                self._publish_locked(0.0, 0.0)  
  
            # 次の動作を開始  
            if not self.active_command and self.command_queue:  
                linear_x, angular_z, duration = (  
                    self.command_queue.popleft()  
                )  
  
                self.command_index += 1  
                self.linear_x = linear_x  
                self.angular_z = angular_z  
                self.deadline = time.monotonic() + duration  
                self.active_command = True  
  
                self.get_logger().info(  
                    f"動作 {self.command_index}/{self.command_count} 開始: "  
                    f"直進 {linear_x} m/s、"  
                    f"旋回 {angular_z} rad/s、"  
                    f"{duration} 秒"  
                )  
  
            # 全動作終了  
            elif (  
                not self.active_command  
                and not self.command_queue  
                and self.command_count > 0  
            ):  
                self.get_logger().info("全動作が完了しました。停止します")  
                self._clear_sequence_locked()  
  
            # 動作中は設定速度、待機中はゼロ速度を周期送信。  
            # ロック内で送信するため、停止直後に古い速度が送信される  
            # スレッド間の競合を避ける。  
            self._publish_locked(self.linear_x, self.angular_z)  
  
  
def validate_commands(content):  
    """動作列を全件検証し、タプルのリストとして返す。"""  
    data = json.loads(content)  
  
    if not isinstance(data, dict) or set(data) != {"commands"}:  
        raise ValueError(  
            'JSONのルートには"commands"のみを指定してください'  
        )  
  
    items = data["commands"]  
  
    if not isinstance(items, list):  
        raise ValueError("commandsは配列である必要があります")  
  
    if not items:  
        raise ValueError("実行可能な動作がありません")  
  
    if len(items) > MAX_COMMANDS:  
        raise ValueError(  
            f"動作数が上限を超えています。最大{MAX_COMMANDS}件です"  
        )  
  
    expected = {"linear_x", "angular_z", "duration_sec"}  
    commands = []  
    total_duration = 0.0  
  
    for index, command in enumerate(items, start=1):  
        if not isinstance(command, dict) or set(command) != expected:  
            raise ValueError(  
                f"{index}番目の動作のJSON項目が不正です"  
            )  
  
        values = []  
  
        for key in ("linear_x", "angular_z", "duration_sec"):  
            value = command[key]  
  
            if isinstance(value, bool) or not isinstance(  
                value, (int, float)  
            ):  
                raise ValueError(  
                    f"{index}番目の{key}は数値である必要があります"  
                )  
  
            value = float(value)  
  
            if not math.isfinite(value):  
                raise ValueError(  
                    f"{index}番目の{key}が有限値ではありません"  
                )  
  
            values.append(value)  
  
        linear_x, angular_z, duration = values  
  
        if not -MAX_LINEAR_SPEED <= linear_x <= MAX_LINEAR_SPEED:  
            raise ValueError(  
                f"{index}番目の直進速度が上限を超えています"  
            )  
  
        if not -MAX_ANGULAR_SPEED <= angular_z <= MAX_ANGULAR_SPEED:  
            raise ValueError(  
                f"{index}番目の旋回速度が上限を超えています"  
            )  
  
        if not MIN_DURATION_SEC <= duration <= MAX_DURATION_SEC:  
            raise ValueError(  
                f"{index}番目の動作時間が範囲外です"  
            )  
  
        total_duration += duration  
        commands.append((linear_x, angular_z, duration))  
  
    if total_duration > MAX_TOTAL_DURATION_SEC:  
        raise ValueError(  
            "合計動作時間が上限を超えています。"  
            f"最大{MAX_TOTAL_DURATION_SEC}秒です"  
        )  
  
    return commands  
  
  
def main():  
    # controller.pyと同じディレクトリのprompt.txtを読む。  
    prompt_path = Path(__file__).resolve().with_name("prompt.txt")  
    pre_prompt = prompt_path.read_text(encoding="utf-8")  
  
    client = OpenAI(  
        base_url=LLM_BASE_URL,  
        api_key="lm-studio",  
        timeout=15.0,  
        max_retries=0,  
    )  
  
    rclpy.init()  
    node = NaturalLanguageController()  
  
    spin_thread = threading.Thread(  
        target=rclpy.spin,  
        args=(node,),  
        daemon=True,  
    )  
    spin_thread.start()  
  
    # LLM処理を別スレッドにし、入力とROS周期送信を止めない。  
    pool = ThreadPoolExecutor(max_workers=1)  
    pending = None  
  
    def process_instruction(text, request_id, current_velocity):  
        try:  
            options = {}  
  
            if USE_JSON_RESPONSE_FORMAT:  
                options["response_format"] = {  
                    "type": "json_object"  
                }  
  
            response = client.chat.completions.create(  
                model=LLM_MODEL,  
                temperature=0,  
                messages=[  
                    {  
                        "role": "system",  
                        "content": pre_prompt,  
                    },  
                    {  
                        "role": "user",  
                        "content": json.dumps(  
                            {  
                                "current_velocity": current_velocity,  
                                "instruction": text,  
                            },  
                            ensure_ascii=False,  
                        ),  
                    },  
                ],  
                **options,  
            )  
  
            content = response.choices[0].message.content or ""  
  
            print(  
                "\nLLMの応答:",  
                repr(content),  
                flush=True,  
            )  
            print(  
                "終了理由:",  
                response.choices[0].finish_reason,  
                flush=True,  
            )  
  
            # 全件検証が完了するまで実行しない。  
            commands = validate_commands(content)  
  
            if node.apply_commands(request_id, commands):  
                print(  
                    f"\n動作列を登録しました: {len(commands)}件",  
                    flush=True,  
                )  
  
                for index, command in enumerate(commands, start=1):  
                    linear_x, angular_z, duration = command  
                    print(  
                        f"  {index}. 直進 {linear_x} m/s、"  
                        f"旋回 {angular_z} rad/s、"  
                        f"{duration} 秒",  
                        flush=True,  
                    )  
            else:  
                print(  
                    "\n古いLLM応答のため、動作列を適用しませんでした",  
                    flush=True,  
                )  
  
        except Exception as exc:  
            # 現在の入力に対応する失敗の場合だけ停止する。  
            if node.fail_request(request_id):  
                print(  
                    f"\n指令を適用できないため停止: {exc}",  
                    flush=True,  
                )  
  
    print("指示を入力してください。")  
    print("停止: stop / 停止")  
    print("終了: exit / quit / 終了")  
    print("新しい指示を入力すると、現在の動作列を停止して置き換えます。")  
  
    try:  
        while rclpy.ok():  
            text = input("> ").strip()  
  
            if not text:  
                continue  
  
            normalized = text.lower()  
  
            if normalized in {"exit", "quit", "終了"}:  
                break  
  
            if normalized in {"stop", "停止", "止まれ", "緊急停止"}:  
                node.stop()  
  
                if pending is not None:  
                    pending.cancel()  
  
                print(  
                    "停止しました。残りの動作も削除しました。",  
                    flush=True,  
                )  
                continue  
  
            request_id, current_velocity = node.begin_request()  
  
            # 未実行の古い依頼はキャンセル。  
            # 実行中のLLM呼び出しは止められなくても、  
            # 応答をrequest_idで無効化する。  
            if pending is not None:  
                pending.cancel()  
  
            pending = pool.submit(  
                process_instruction,  
                text,  
                request_id,  
                current_velocity,  
            )  
  
    except (KeyboardInterrupt, EOFError):  
        pass  
  
    finally:  
        # 最初にロボットを停止し、LLM応答を無効化する。  
        node.close()  
  
        pool.shutdown(  
            wait=False,  
            cancel_futures=True,  
        )  
  
        node.timer.cancel()  
  
        if rclpy.ok():  
            rclpy.shutdown()  
  
        spin_thread.join()  
        node.destroy_node()  
  
  
if __name__ == "__main__":  
    main()  