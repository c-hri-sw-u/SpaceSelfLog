import SwiftUI

@main
struct SpaceSelfLogApp: App {
    @StateObject private var viewModel = AppViewModel()
    @StateObject private var notificationManager = NotificationManager.shared

    var body: some Scene {
        WindowGroup {
            ContentView(viewModel: viewModel)
                .onAppear {
                    // Request notification permission
                    notificationManager.requestPermission()
                    
                    viewModel.startServerIfNeeded()
                    // Start camera with saved selection
                    if let selectedCamera = viewModel.selectedCamera {
                        viewModel.switchCamera(to: selectedCamera)
                    }
                }
        }
    }
}