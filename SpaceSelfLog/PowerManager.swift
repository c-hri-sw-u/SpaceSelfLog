import UIKit

final class PowerManager {
    private var originalBrightness: CGFloat = 0.5

    private func currentScreen() -> UIScreen? {
        (UIApplication.shared.connectedScenes.first as? UIWindowScene)?.screen
    }

    func enterLowPowerMode() {
        guard let screen = currentScreen() else { return }
        originalBrightness = screen.brightness
        screen.brightness = 0.01 // 1%
        UIApplication.shared.isIdleTimerDisabled = true
    }

    func exitLowPowerMode() {
        guard let screen = currentScreen() else { return }
        screen.brightness = originalBrightness
        UIApplication.shared.isIdleTimerDisabled = false
    }
    
    // MARK: - Battery Management
    func getBatteryLevel() -> Float {
        UIDevice.current.isBatteryMonitoringEnabled = true
        return UIDevice.current.batteryLevel
    }
    
    func getBatteryState() -> UIDevice.BatteryState {
        UIDevice.current.isBatteryMonitoringEnabled = true
        return UIDevice.current.batteryState
    }
    
    func getBatteryInfo() -> (level: Float, state: String) {
        let level = getBatteryLevel()
        let state = getBatteryState()
        
        let stateString: String
        switch state {
        case .unknown:
            stateString = "Unknown"
        case .unplugged:
            stateString = "Unplugged"
        case .charging:
            stateString = "Charging"
        case .full:
            stateString = "Full"
        @unknown default:
            stateString = "Unknown"
        }
        
        return (level: level, state: stateString)
    }
}