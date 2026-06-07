# 📡 直播源质量审计系统

一堆免费的直播源，看着很多，能顺利看的不多，怎么办？

这个程序就是来解决这个问题

下载脚本到ubuntu

python main.py

http://ip:5000



<img width="1250" height="513" alt="ScreenShot_2026-05-31_222027_016" src="https://github.com/user-attachments/assets/49400fc7-20e1-48c9-bb6c-1aa6a5ad4aeb" />

<img width="1178" height="602" alt="捕111获" src="https://github.com/user-attachments/assets/770be9a8-32d3-4533-a476-e6a3b49cd9e9" />

<img width="722" height="399" alt="捕111333获" src="https://github.com/user-attachments/assets/a59e2d81-e598-4063-83b5-62e6443bf3a2" />



参数名称,用途定义
timeout_video,FFmpeg 总超时。当调用 FFmpeg 进行视频流分析时，最长等待时间。如果超过此时间还没吐出视频信息，直接判定为死链。

timeout_stable,测速持续时间。决定在“测速”阶段，我们要连续拉流多久（秒）来观察其平稳性。

connect_timeout_basic,TCP 连接超时。请求源站 IP 时的 TCP 三次握手最大时间。

read_timeout_basic,TCP 读取超时。建立连接后，等待源站开始发送第一个字节数据的最大时间。

min_speed_dead,死链流速线。如果测速期间的平均流速低于此值，认定为“断流/死链”。

max_jitter_dead,抖动生死线。拉流时数据包到达的时间差（抖动），如果波动过大，说明网络极其不稳定，不可用。

min_speed_normal,高清流速线。虽然不断流，但如果速度达不到这个值，画质通常很差或卡顿，属于“质量不达标”。

max_jitter_normal,抖动合格线。容忍的最大网络波动范围。

min_height,分辨率过滤。审计出的视频垂直高度（像素）。例如 720p 对应 720。低于此数值会被过滤。

min_speed_ratio,速度波动比率（通常用于算法预留），代表流速的稳定性比例。

