# TurtleBot3 自然言語制御プログラムの仕様・操作方法  
  
## 1. 概要  
  
本プログラムは、ROS 2とGazebo上のTurtleBot3を自然言語で簡易的に操作指示するプログラムです。  
こちらを参考にさせていただきました。  
[ChatGPT APIを使って自然言語の指示でGazebo上のTurtleBot3を制御する](https://qiita.com/porizou1/items/a085d20e936946330540)  
  
ユーザーの指示をLLMが速度指令のJSONへ変換し、Python側で検証した後、ROSの `/cmd_vel` に送信します。  

  
ユーザーの指示例：  
  
```text  
0.1m/sで10秒間前に進んだ後、左に0.3rad/sで2秒間旋回して  
```  
  
実行順序：  
  
1. 0.1 m/sで10秒間前進  
2. 左に0.3 rad/sで2秒間旋回  
3. 停止  

## 2. 実行環境  

本検証では、Windows 11上のLM StudioでLLMを実行し、WSL上のUbuntu 24.04からAPI経由で利用した。  

| 項目 | 使用環境・ソフトウェア | 役割 |  
|---|---|---|  
| ホストOS | Windows 11 | LM StudioおよびWSLの実行 |  
| Linux実行基盤 | WSL 3.0.3.0 | Ubuntuの実行 |  
| Linux OS | Ubuntu 24.04.5 LTS | ROS 2および制御プログラムの実行 |  
| ROS | ROS 2 Jazzy | ロボット制御と速度指令の送信 |  
| LLM実行ソフトウェア | LM Studio 0.4.26 | LLMの読み込みとAPIサーバーの提供 |  
| LLMモデル | Ornith1.5-9B-Q4_K_M | 自然言語指示から動作列JSONを生成 |  
| 制御プログラム | `controller.py` | 入力受付、LLM通信、検証、順次実行 |  
| プロンプトファイル | `prompt.txt` | LLMへの変換ルールの指定 |  
| シミュレーション | Gazebo 8.15.0／TurtleBot3 | 生成した指令による動作確認 |  



  
## 3. システム構成  

```text  
Windows 11  
│  
├── LM Studio  
│   ├── LLM：Ornith1.5-9B  
│   └── OpenAI互換APIサーバー  
│               ▲  
│               │ HTTPによるAPI通信  
│               ▼  
└── WSL  
    └── Ubuntu 24.04  
        ├── ROS 2 Jazzy  
        ├── controller.py  
        │   ├── 自然言語の入力受付  
        │   ├── LLMへの問い合わせ  
        │   ├── 動作列JSONの検証  
        │   └── 動作の順次実行  
        ├── prompt.txt  
        └── Gazebo／TurtleBot3  
                    ▲  
                    │ /cmd_vel  
                    │ TwistStamped  
                    └── controller.pyから速度指令を受信  
```  
  
LLMの推論はWindows側、JSONの検証とロボット制御はUbuntu側で実行する。  

#### 手続きの流れ  
```text  
ユーザーが自然言語で入力  
        ↓  
現在の動作列を停止し、古いLLM応答を無効化  
        ↓  
LLMへ1回問い合わせ  
        ↓  
LLMが動作列のJSONを生成  
        ↓  
Pythonで全動作を検証  
        ↓  
検証済みの動作列をキューへ登録  
        ↓  
ROSタイマーで速度指令を周期送信  
        ↓  
指定時間ごとに次の動作へ切り替え  
        ↓  
全動作完了後に停止  
```  
  
JSONそのものをROSへ送るのではなく、各動作を `TwistStamped` に変換して送信する。  
  

## 4. Windows側の構成  
  
### 4.1 LM Studio  
  
Windows 11にインストールしたLM Studioで、Ornith1.5-9Bを読み込み、API経由で利用できる状態にした。  
  
LM Studioは、Ubuntu側の制御プログラムに対してOpenAI互換APIを提供する。  
  
### 4.2 LLMの役割  
  
LLMは自然言語の指示を解釈し、実行順に並べた動作列のJSONを生成する。  
  
入力例：  
  
```text  
0.1m/sで10秒間前に進んだ後、左に0.3rad/sで2秒間旋回して  
```  
  
出力例：  
  
```json  
{  
  "commands": [  
    {  
      "linear_x": 0.1,  
      "angular_z": 0.0,  
      "duration_sec": 10.0  
    },  
    {  
      "linear_x": 0.0,  
      "angular_z": 0.3,  
      "duration_sec": 2.0  
    }  
  ]  
}  
```  
  
LLMはJSONの生成を担当し、ROSの速度指令を直接送信しない。  
  
## 5. Ubuntu側の構成  
  
### 5.1 ROS環境  
  
WSL上のUbuntu 24.04にROS 2 Jazzyを構築し、制御プログラムとシミュレーションを実行する。  
  
### 5.2 使用ファイル  
  
```text  
作業ディレクトリ/  
├── controller.py  
└── prompt.txt  
```  
  
| ファイル | 内容 |  
|---|---|  
| `controller.py` | LLMへの問い合わせ、JSON検証、動作キュー管理、ROS速度指令の送信 |  
| `prompt.txt` | JSON形式、動作の解釈方法、既定値、制限値の指定 |  
  
## 6. 指令JSONの仕様  
  
### 6.1 基本形式  
  
```json  
{  
  "commands": [  
    {  
      "linear_x": 0.1,  
      "angular_z": 0.0,  
      "duration_sec": 10.0  
    },  
    {  
      "linear_x": 0.0,  
      "angular_z": 0.3,  
      "duration_sec": 2.0  
    }  
  ]  
}  
```  
  
`commands` の先頭から順番に実行する。  
  
単一動作の場合も、同じ形式で1件だけ格納する。  
  
```json  
{  
  "commands": [  
    {  
      "linear_x": 0.1,  
      "angular_z": 0.0,  
      "duration_sec": 3.0  
    }  
  ]  
}  
```  
  
### 6.2 各項目の意味  
  
| キー | 内容 | 単位 | 符号の意味 |  
|---|---|---|---|  
| `linear_x` | 前後方向の速度 | m/s | 正：前進、負：後退 |  
| `angular_z` | 鉛直軸まわりの旋回速度 | rad/s | 正：左旋回、負：右旋回 |  
| `duration_sec` | 指令の継続時間 | 秒 | 正の動作時間 |  
  
### 6.3 順次動作と同時動作  
  
次の指示は、前進と旋回を別々に実行する。  
  
```text  
前に進んだ後、左に旋回して  
```  
  
一方、次のように同時動作が明示された場合は、直進速度と旋回速度の両方を非ゼロにする。  
  
```text  
0.1m/sで前進しながら、左に0.3rad/sで3秒間旋回して  
```  
  
期待するJSON：  
  
```json  
{  
  "commands": [  
    {  
      "linear_x": 0.1,  
      "angular_z": 0.3,  
      "duration_sec": 3.0  
    }  
  ]  
}  
```  
  
実際の解釈はLLMに依存するため、出力ログも確認する必要がある。  
  
## 7. 制限値と既定値  
  
### 7.1 Python側の制限  
  
| 項目 | 許容範囲・上限 |  
|---|---|  
| 直進速度 | -0.3～0.3 m/s |  
| 旋回速度 | -1.0～1.0 rad/s |  
| 1動作の時間 | 0.1～30.0秒 |  
| 動作数 | 最大10件 |  
| 合計動作時間 | 最大120秒 |  
  
これらは `controller.py` 冒頭の定数で設定。  
  
```python  
MAX_LINEAR_SPEED = 0.3  
MAX_ANGULAR_SPEED = 1.0  
MIN_DURATION_SEC = 0.1  
MAX_DURATION_SEC = 30.0  
MAX_COMMANDS = 10  
MAX_TOTAL_DURATION_SEC = 120.0  
```  
  
範囲外の値を自動補正するのではなく、指令を拒否して停止する。  
  
### 7.2 プロンプト側の既定値  
  
| 省略された項目 | 既定値 |  
|---|---|  
| 動作時間 | 3秒 |  
| 前進・後退の速度 | 絶対値0.1 m/s |  
| 旋回速度 | 絶対値0.3 rad/s |  
  
既定値はLLMに与えるプロンプトで定めている。  
  
### 7.3 解釈できない指示  
  
プロンプトでは、解釈できない指示や制限を超える指示に対して、次を返すよう指定している。  
  
```json  
{  
  "commands": []  
}  
```  
  
Python側は空の動作列を拒否し、停止状態を維持する。  
  
## 8. JSONの検証仕様  
  
`validate_commands()` で、実行前に全件を検証する。  
  
- ルートがJSONオブジェクトであること  
- ルートのキーが `commands` のみであること  
- `commands` が空でない配列であること  
- 動作数が上限以内であること  
- 各動作のキーが指定の3項目だけであること  
- 値が数値であること  
- 真偽値や非有限値でないこと  
- 速度と時間が許容範囲内であること  
- 合計動作時間が上限以内であること  
  
**1件でも不正な動作があれば、その動作列全体を実行しない。**  
  
  
## 9. ROS側の制御仕様  
  
| 項目 | 設定 |  
|---|---|  
| ノード名 | `natural_language_controller` |  
| 速度指令トピック | `/cmd_vel` |  
| メッセージ型 | `geometry_msgs/msg/TwistStamped` |  
| フレームID | `base_link` |  
| 直進速度 | `msg.twist.linear.x` |  
| 旋回速度 | `msg.twist.angular.z` |  
| 送信周期 | 0.1秒 |  
| QoS履歴 | `KEEP_LAST`、深さ10 |  
| QoS信頼性 | `RELIABLE` |  
| 待機中 | ゼロ速度を周期送信 |  
  
環境側のメッセージ型は、次のコマンドで確認可能。  
  
```bash  
ros2 topic type /cmd_vel  
```  
  
別の環境で `Twist` が必要な場合は、コード側の型とフィールドを変更する必要がある。  
  
## 10. 順次実行の仕組み  
  
1. 検証済みの全動作をキューへ登録する  
2. タイマーが先頭の動作を開始する  
3. 設定速度を0.1秒周期で送信する  
4. 指定時間の経過を判定する  
5. ゼロ速度を送信し、次の動作へ切り替える  
6. 全動作が終了したら停止状態に戻る  
  
  
## 11. スレッドと古い応答の管理  
  
本プログラムでは、以下を分離している。  
  
| 処理 | 実行場所 |  
|---|---|  
| ユーザー入力 | メインスレッド |  
| ROSタイマー・周期送信 | ROSのspinスレッド |  
| LLMへの問い合わせ | `ThreadPoolExecutor` |  
  
これにより、LLMの応答待ち中や動作実行中にも停止入力を受け付けることが可能。  
  
### リクエストID  
  
新しい指示、停止、終了などでリクエストIDを更新する。LLM応答のIDが現在のIDと一致しなければ、その応答は適用しない。  
  
**停止後に遅れて届いたLLM応答から、ロボットが動き出すことを防いでいる。**  
  
ただし、実行中のLLM通信そのものを即座に中止する仕組みではない。古い問い合わせが完了するまで、新しい問い合わせが待つ場合がある。  
  
## 12. LLM接続設定  
  
`controller.py` の設定：  
  
```python  
LLM_BASE_URL = "http://x.x.x.x:1234/v1"  
LLM_MODEL = "local-model"  
USE_JSON_RESPONSE_FORMAT = False  
```  
  
接続先やモデル名は、使用するLLMサーバーに合わせて変更すること。  
   
  
## 13. 起動方法  
  
### 13.1 LLMサーバーを準備する  
  
LM StudioなどのLLMサーバーを起動し、モデルを読み込む。  
  
  
### 13.2 Gazeboを起動する  
  
ROS環境を読み込んだターミナルで実行。  
  
```bash  
ros2 launch turtlebot3_gazebo turtlebot3_world.launch.py  
```  
  
### 13.3 制御プログラムを起動する  
  
別のターミナルで必要なROS環境とPython環境を準備し、以下を実行し。  
  
```bash  
python3 controller.py  
```  
  
  
## 14. 操作方法  
  
### 14.1 単一動作  
  
```text  
0.1m/sで3秒間前に進んで  
```  
  
### 14.2 複数動作  
  
```text  
0.1m/sで10秒間前に進んだ後、左に0.3rad/sで2秒間旋回して  
```  
  
### 14.3 後退と右旋回  
  
```text  
0.1m/sで2秒間後退した後、右に0.3rad/sで3秒間旋回して  
```  
  
### 14.4 動作中に新しい指示を入力する  
  
新しい指示を受け付けると、次の処理が実行される。  
  
1. 現在の動作を停止  
2. 残りの動作キューを削除  
3. 古いLLM応答を無効化  
4. 新しい指示をLLMへ送信  
5. 応答を検証して、新しい動作列を実行  
 
  
### 14.5 停止する  
  
次のいずれかを入力。  
  
```text  
stop  
```  
  
```text  
停止  
```  
  
```text  
止まれ  
```  
  
```text  
緊急停止  
```  
  
### 14.6 終了する  
  
次のいずれかを入力。  
  
```text  
exit  
```  
  
```text  
quit  
```  
  
```text  
終了  
```  
  
または、ターミナルで **Ctrl+C** を入力。  
   

## 15. Gazeboを初期状態へ戻す方法  
  
停止してもプロセスが残っていることがあった。その場合の対応。   
    
  
### 15.1 残っているプロセスを確認する  
  
```bash  
pgrep -af 'gz sim'  
```  
  
### 15.2 対象プロセスを終了する  
  
表示された現在のPIDを指定。  
  
```bash  
kill -TERM <対象PID>  
```  
  
複数ある場合：  
  
```bash  
kill -TERM <PID1> <PID2> <PID3>  
```  
  
数秒後に再確認。  
  
```bash  
pgrep -af 'gz sim'  
```  
  
対象プロセスが残っている場合に限り、強制終了する。  
  
```bash  
kill -KILL <残っている対象PID>  
```  
  
### 15.3 Gazeboを再起動する  
  
```bash  
ros2 launch turtlebot3_gazebo turtlebot3_world.launch.py  
```  
   