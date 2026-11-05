# GlassRadio V44：录屏接入与算法对照（新编写的兼容实现）

> **重要**：这里上传的是根据已存档 V44 协议/配置另行编写的 Python 录屏评测工具，**不是丢失的 V44 原版 C++ 源码**，运行结果不能命名为历史 `v44_results.csv`，也不能声称复现了原报告统计数字。

## 1. 准备录屏

将自己拥有权限的 MP4/MOV 放到 `recordings/`，建议至少 3 段**互不重叠的 session**。请勿上传含私人账号、聊天和第三方隐私的录屏到公开仓库。

## 2. 安装与运行

Linux / macOS：

```bash
cd glassradio-v44
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m unittest discover -s tests -v
python glassradio_v44_portable.py --config video_config.json --videos recordings/session1.mp4 recordings/session2.mp4 --out runs/v44_video_trial
```

Windows PowerShell：

```powershell
cd glassradio-v44
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
py -m unittest discover -s tests -v
py glassradio_v44_portable.py --config video_config.json --videos recordings/session1.mp4 --out runs/v44_video_trial
```

如 PowerShell 禁止执行脚本，可以直接用 `.venv\Scripts\python.exe` 运行上述 Python 命令。

## 3. 输出文件

- `v44_video_results.csv`：每个 session、观测方式、K、算法的一行统计结果。
- `v44_video_updates.csv`：逐 tile 更新的协议模式、传输字节、处理器计时、缓存写入和无损检查。
- `session_manifest.csv`：原录屏文件 SHA-256、采样帧数与变化图块数。
- `config_used.json`：本次运行参数副本。
- `verification.json`：是否全部无损、是否全部满足接收端工作量与写入限制。

## 4. 研究边界

1. 录屏帧缩小到 256×144 并二值化，切成 8×8 图块；只保证**处理后的二值图块**无损，不保证原 RGB 视频无损。
2. `random` 和 `block` 遮挡是对真实录屏像素施加的**合成掩码**，不是实际检测的遮挡。算法只看到同一份可见掩码和可见像素，编码器随后读取完整二值目标。
3. 发送字节包含五模式包与每次 tile 更新固定 **10 B 的建模位置/长度元数据**；尚无真实 TCP/UDP 协议、重传或无线能耗。
4. CPU 是 Python `process_time_ns`，**不能**直接与原 V44 C++ 的 50 μs 诊断时限比较。
5. 一条录屏即一个统计单元；不要把成千上万个相邻 tile 当作独立样本；未实现学习式模型训练/校准/测试。
6. 原版历史冻结配置保存在 `v44_original_frozen_config.json`，与本工具的 `video_config.json` 不等价。真正历史 V44 完整复现必须取得原版 native sender、原始 `v44_results.csv` 和数据包样本。

## 5. 后续验收

拿到真实 session 后，应先冻结划分和主指标，再增加 canonical SIEVE/GDS、学习模型、完整 RGB 无损方案以及原生 CPU 与网络测量。现有实现是可运行的工程基线，不是原创算法贡献的证据。
