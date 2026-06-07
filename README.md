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


🔴 情况 A：好用的直播源被大量删除了（过滤太严）
调整方向： 放宽参数（即减小 min_speed，增大 timeout 和 jitter）。

具体动作：

将 min_speed_dead 和 min_speed_normal 的数值向下调（例如国内可以从 100KB 下调到 50KB）。

将 max_jitter_dead 和 max_jitter_normal 的数值向上调（例如从 3.0 调到 5.0）。

增加 timeout_video（例如从 20s 加到 40s），让那些加载慢的源有更多时间显影。

🟢 情况 B：审计出的直播源全是马赛克、加载极其缓慢（过滤太松）
调整方向： 收紧参数（即提高流速要求，降低超时容忍度）。

具体动作：

提高 min_speed_normal 的要求（例如调高到 300KB/s），确保通过的都是高清源。

减小 max_jitter_dead，如果抖动超过 2s 就直接干掉，强制要求网速平稳。

调高 min_height，要求所有通过的源至少是 1080p。

💡 特别提示：
分治策略：如果你发现国内源很好，但港台源总是无法通过，只调 HKTW_CONFIG 即可，不要动国内参数，这样能保证审计系统的颗粒度最细。

网络环境决定一切：如果你运行系统的机器本身网速较慢，或者服务器位于海外，那么所有的 min_speed 参数都应该调得比默认值更保守（更低），否则会造成大量的“误杀”。

