# SpaceSelfLog MVP

轻量级 iPhone 监控录像 App（MVP，MVVM 结构）。

## 功能概述

- 摄像头录像控制：支持广角（1x）/ 超广角（0.5x）
- 省电模式（伪熄屏）：黑屏、亮度降至 1%、禁用自动锁屏、计时器显示
- 电脑端实时监控：同一局域网浏览器访问，MJPEG 流媒体，远程控制开始/停止/切换摄像头

## 架构

- MVVM：`AppViewModel` 统一编排业务状态
- Model：`CameraManager`（AVFoundation）、`StreamServer`（HTTP + MJPEG）、`PowerManager`（亮度/锁屏）
- View：`ContentView` 黑底白字 UI

## 隐私权限与配置

项目使用 Xcode 生成 Info.plist（`GENERATE_INFOPLIST_FILE = YES`）。你需要在 Target 的 Info 设置或 `project.pbxproj` Build Settings 中添加以下键值：

- `NSCameraUsageDescription`（Privacy - Camera Usage Description）：例如“用于录像与局域网实时监控”
- 建议：`NSLocalNetworkUsageDescription`（Privacy - Local Network Usage Description）：例如“用于在同一局域网内提供监控画面访问”

说明：MVP 当前未采集音频，后续如需录音请添加 `NSMicrophoneUsageDescription`。

## 运行与使用

1. 在 Xcode（iOS 14+）编译并安装到 iPhone（建议 iPhone 12）
2. 打开 App：
   - 选择摄像头（广角/超广角）
   - 点击 `Record` 启动录像与省电模式（黑屏 + 计时器）
3. 在同一 Wi-Fi 的电脑浏览器打开 App 显示的地址（例如 `http://192.168.1.100:8080`）：
   - 页面含实时 MJPEG 画面（`/stream`）
   - 控制按钮：开始/停止、切换广角/超广角
   - 状态信息：录制时长、设备名、连接地址、当前摄像头等

### HTTP 端点

- `GET /`：监控页面（内置控制按钮与状态刷新）
- `GET /stream`：MJPEG 流（Content-Type: `multipart/x-mixed-replace; boundary=frame`）
- `GET /start`：开始录像
- `GET /stop`：停止录像
- `GET /switch?camera=wide|ultra`：切换摄像头
- `GET /status`：JSON 状态信息

## 质量档位（后续）

MVP 采用 MJPEG，后续可扩展画质选择（1080p/720p/480p）、H.264/AAC 文件录制或升级为 WebRTC 以降低延迟。

## 注意事项

- 请确保手机与电脑在同一局域网/Wi-Fi
- iOS 会限制后台网络与相机访问，MVP 通过“伪熄屏”降低亮度但保持前台运行
- 若无法访问，请检查本机 IP 与端口占用情况