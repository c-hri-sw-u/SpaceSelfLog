import Foundation
import UserNotifications
import Combine

// 通知代理，确保前台也能显示通知
class NotificationDelegate: NSObject, UNUserNotificationCenterDelegate {
    static let shared = NotificationDelegate()
    
    private override init() {
        super.init()
    }
    
    // 前台显示通知
    func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification, withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void) {
        // 在前台显示横幅、声音和角标
        completionHandler([.banner, .sound, .badge])
    }
    
    // 处理通知点击
    func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse, withCompletionHandler completionHandler: @escaping () -> Void) {
        completionHandler()
    }
}

final class NotificationManager: ObservableObject {
    static let shared = NotificationManager()
    
    @Published var isAuthorized = false
    
    private init() {
        checkAuthorizationStatus()
        setupNotificationDelegate()
    }
    
    // 设置通知代理，确保前台也能显示通知
    private func setupNotificationDelegate() {
        UNUserNotificationCenter.current().delegate = NotificationDelegate.shared
    }
    
    // 请求通知权限
    func requestPermission() {
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound, .badge]) { granted, error in
            DispatchQueue.main.async {
                self.isAuthorized = granted
                if let error = error {
                    print("NotificationManager: Permission request failed: \(error.localizedDescription)")
                } else {
                    print("NotificationManager: Permission granted: \(granted)")
                }
            }
        }
    }
    
    // 检查当前权限状态
    private func checkAuthorizationStatus() {
        UNUserNotificationCenter.current().getNotificationSettings { settings in
            DispatchQueue.main.async {
                self.isAuthorized = settings.authorizationStatus == .authorized
            }
        }
    }
    
    // 发送API失败通知
    func sendAPIFailureNotification(error: String) {
        guard isAuthorized else {
            print("NotificationManager: Not authorized to send notifications")
            return
        }
        
        let content = UNMutableNotificationContent()
        content.title = "SpaceSelfLog API Error"
        content.body = "Gemini API调用失败: \(error)"
        content.sound = .default
        content.badge = 1
        
        // 设置通知标识符，用于去重
        let identifier = "api_failure_\(Date().timeIntervalSince1970)"
        
        // 立即触发通知（最小间隔1秒）
        let trigger = UNTimeIntervalNotificationTrigger(timeInterval: 1.0, repeats: false)
        let request = UNNotificationRequest(identifier: identifier, content: content, trigger: trigger)
        
        UNUserNotificationCenter.current().add(request) { error in
            if let error = error {
                print("NotificationManager: Failed to schedule notification: \(error.localizedDescription)")
            } else {
                print("NotificationManager: API failure notification scheduled")
            }
        }
    }
    
    // 发送连续失败警告通知
    func sendContinuousFailureWarning(failureCount: Int) {
        guard isAuthorized else { return }
        
        let content = UNMutableNotificationContent()
        content.title = "SpaceSelfLog 连续错误警告"
        content.body = "API已连续失败\(failureCount)次，请检查网络连接和API配置"
        content.sound = .default
        content.badge = NSNumber(value: failureCount)
        
        let identifier = "continuous_failure_warning"
        let trigger = UNTimeIntervalNotificationTrigger(timeInterval: 1.0, repeats: false)
        let request = UNNotificationRequest(identifier: identifier, content: content, trigger: trigger)
        
        UNUserNotificationCenter.current().add(request) { error in
            if let error = error {
                print("NotificationManager: Failed to schedule warning notification: \(error.localizedDescription)")
            } else {
                print("NotificationManager: Continuous failure warning scheduled")
            }
        }
    }
    
    // 清除所有通知
    func clearAllNotifications() {
        UNUserNotificationCenter.current().removeAllPendingNotificationRequests()
        UNUserNotificationCenter.current().removeAllDeliveredNotifications()
        UNUserNotificationCenter.current().setBadgeCount(0)
    }
}