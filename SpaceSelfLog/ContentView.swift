import SwiftUI

extension DateFormatter {
    static let shortTime: DateFormatter = {
        let formatter = DateFormatter()
        formatter.timeStyle = .short
        return formatter
    }()
}

// MARK: - Design System
extension Color {
    static let primaryText = Color.white
    static let secondaryText = Color.white.opacity(0.6)
    static let accentColor = Color.green
}

extension Font {
    static let regularText = Font.body
    static let smallText = Font.caption
}

struct ContentView: View {
    @ObservedObject var viewModel: AppViewModel
    @State private var showResolutionMenu = false
    @State private var showAISettings = false
    @State private var tempAPIKey = ""
    @State private var tempPrompt = ""
    @State private var tempInterval: Double = 30.0
    @State private var isTestingAPIKey = false

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()
            VStack(spacing: 24) {
                // Title / version
                VStack(spacing: 8) {
                    Text("SpaceSelfLog")
                        .font(.regularText)
                        .fontWeight(.semibold)
                        .foregroundColor(.primaryText)
                }
                .padding(.top, 32)
                
                // AI Analysis Section
                VStack(spacing: 12) {
                    HStack {
                        Text("AI Smart Analysis")
                            .font(.regularText)
                            .fontWeight(.medium)
                            .foregroundColor(.primaryText)
                        Spacer()
                        Button(action: { showAISettings.toggle() }) {
                            Image(systemName: "gear")
                                .font(.regularText)
                                .foregroundColor(.primaryText)
                        }
                    }
                    
                    HStack(spacing: 12) {
                        // AI Analysis Auto Mode Toggle
                        VStack(alignment: .leading, spacing: 4) {
                            HStack {
                                Text("Auto Analysis on Record")
                                    .font(.smallText)
                                    .foregroundColor(.primaryText)
                                Spacer()
                                Toggle("", isOn: Binding(
                                    get: { viewModel.aiAnalysisAutoMode },
                                    set: { _ in viewModel.toggleAIAnalysisAutoMode() }
                                ))
                                .disabled(viewModel.geminiAPIKey.isEmpty)
                            }
                        }
                        Spacer()
                    }
                    
                    // Current Analysis Status
                    if viewModel.isAIAnalysisEnabled {
                        HStack {
                            Text("AI Analysis Running")
                                .font(.smallText)
                                .foregroundColor(.accentColor)
                            Spacer()
                        }
                    }
                    
                    // Latest Result Display
                    if let result = viewModel.latestAnalysisResult {
                        VStack(alignment: .leading, spacing: 4) {
            Text("Latest Result: \(result.formattedOutput.activityLabel)")
                                .font(.smallText)
                                .foregroundColor(.primaryText)
                            Text(DateFormatter.shortTime.string(from: result.captureTime))
                                .font(.smallText)
                                .foregroundColor(.secondaryText)
                        }
                    }
                    
                    // Error Display
                    if let error = viewModel.aiAnalysisError {
                        Text(error)
                            .font(.smallText)
                            .foregroundColor(.red)
                            .padding(.horizontal, 12)
                            .padding(.vertical, 6)
                            .background(Color.red.opacity(0.1))
                            .cornerRadius(6)
                    }
                }

                // Camera selection
                VStack(spacing: 12) {
                    HStack {
                            Text("Camera Settings")
                                .font(.regularText)
                                .fontWeight(.medium)
                                .foregroundColor(.primaryText)
                            Spacer()
                        }
                    HStack(spacing: 8) {
                        ForEach(viewModel.availableCameras, id: \.self) { cam in
                            Button(action: { viewModel.switchCamera(to: cam) }) {
                                Text(label(for: cam))
                                    .font(.smallText)
                                    .lineLimit(1)
                                    .padding(.horizontal, 12).padding(.vertical, 8)
                                    .background(Color.white)
                                    .foregroundColor(.black)
                                    .cornerRadius(6)
                                    .overlay(
                                        RoundedRectangle(cornerRadius: 6)
                                            .stroke(viewModel.selectedCamera == cam ? Color.accentColor : Color.clear, lineWidth: 2)
                                    )
                            }
                        }
                        
                        // Resolution selection button
                        Menu {
                            ForEach(viewModel.availableResolutions, id: \.self) { resolution in
                                Button(action: { viewModel.switchResolution(to: resolution) }) {
                                    HStack {
                                        Text(resolution.displayName)
                                        if viewModel.selectedResolution == resolution {
                                            Image(systemName: "checkmark")
                                        }
                                    }
                                }
                            }
                        } label: {
                            HStack(spacing: 4) {
                                Text("Resolution")
                                    .font(.smallText)
                                    .lineLimit(1)
                                Image(systemName: "chevron.right")
                                    .font(.smallText)
                            }
                            .padding(.horizontal, 12).padding(.vertical, 8)
                            .background(Color.white)
                            .foregroundColor(.black)
                            .cornerRadius(6)
                        }
                        
                        // Rotation button
                        Button(action: { viewModel.rotateCamera() }) {
                            Image(systemName: "rotate.right")
                                .font(.smallText)
                                .padding(.horizontal, 12).padding(.vertical, 8)
                                .background(Color.white)
                                .foregroundColor(.black)
                                .cornerRadius(6)
                        }
                    }
                }

                // Server address & network
                VStack(spacing: 8) {
                    HStack {
                        Text("Local Network")
                            .font(.regularText)
                            .fontWeight(.medium)
                            .foregroundColor(.primaryText)
                        Spacer()
                    }
                    
                    HStack(spacing: 16) {
                        // Connection Status with address
                        HStack {
                            Circle()
                                .fill(!viewModel.serverAddress.isEmpty ? Color.accentColor : Color.red)
                                .frame(width: 8, height: 8)
                            
                            Group {
                                if #available(iOS 15.0, *) {
                                    Text(viewModel.serverAddress.isEmpty ? "Preparing connection address..." : viewModel.serverAddress)
                                        .font(.smallText)
                                        .foregroundColor(.primaryText)
                                        .textSelection(.enabled)
                                } else {
                                    Text(viewModel.serverAddress.isEmpty ? "Preparing connection address..." : viewModel.serverAddress)
                                        .font(.smallText)
                                        .foregroundColor(.primaryText)
                                }
                            }
                            
                            Spacer()
                        }
                        Spacer()
                        // Network status
                        HStack {
                            Text(viewModel.networkStatus)
                                .font(.smallText)
                                .foregroundColor(.secondaryText)
                            Spacer()
                        }
                    }
                }

                // Record / End
                if viewModel.isRecording {
                    VStack(spacing: 16) {
                        VStack(spacing: 16) {
                            // End button
                            Button(action: {
                                HapticManager.single()
                                viewModel.stopRecording()
                            }) {
                                Text("End")
                                    .font(.regularText)
                                    .fontWeight(.bold)
                                    .lineLimit(1)
                                    .padding(.horizontal, 20).padding(.vertical, 12)
                                    .background(Color.white)
                                    .foregroundColor(.black)
                                    .cornerRadius(6)
                            }
                            // Record duration
                            Text(viewModel.durationString)
                                .font(.regularText)
                                .fontWeight(.bold)
                                .foregroundColor(.primaryText)
                        }
                        // Pause/Resume button
                        Button(action: {
                                if viewModel.isPaused {
                                    HapticManager.double()
                                    viewModel.resumeRecording()
                                } else {
                                    HapticManager.single()
                                    viewModel.pauseRecording()
                                }
                            }) {
                                Text(viewModel.isPaused ? "Resume" : "Pause")
                                    .font(.regularText)
                                    .fontWeight(.bold)
                                    .lineLimit(1)
                                    .frame(maxWidth: .infinity)
                                    .frame(maxHeight: .infinity)
                                    .background(Color.black)
                                    .foregroundColor(.white)
                                    .cornerRadius(6)
                                    .overlay(
                                        RoundedRectangle(cornerRadius: 6)
                                            .stroke(Color.white, lineWidth: 2)
                                    )
                            }
                    }
                } else {
                    // Record button
                    Button(action: {
                        HapticManager.single()
                        viewModel.startRecording()
                    }) {
                        Text("Record")
                            .font(.regularText)
                            .fontWeight(.bold)
                            .lineLimit(1)
                            .frame(maxWidth: .infinity)
                            .frame(maxHeight: .infinity)
                            .background(Color.black)
                            .foregroundColor(.white)
                            .cornerRadius(6)
                            .overlay(
                                RoundedRectangle(cornerRadius: 6)
                                    .stroke(Color.white, lineWidth: 2)
                            )
                    }
                }
            }
        }
        .sheet(isPresented: $showAISettings) {
            AISettingsView(
                viewModel: viewModel,
                tempAPIKey: $tempAPIKey,
                tempPrompt: $tempPrompt,
                tempInterval: $tempInterval,
                isTestingAPIKey: $isTestingAPIKey
            )
        }
        .onAppear {
            // Initialize temp values with current settings
            tempAPIKey = viewModel.geminiAPIKey
            tempPrompt = viewModel.aiAnalysisPrompt
            tempInterval = viewModel.aiAnalysisInterval
        }
        .onChange(of: viewModel.aiAnalysisInterval) { newInterval in
            // Update temp interval when ViewModel changes (e.g., from web interface)
            if !showAISettings {
                tempInterval = newInterval
            }
        }
        .onChange(of: viewModel.aiAnalysisPrompt) { newPrompt in
            // Update temp prompt when ViewModel changes (e.g., from web interface)
            if !showAISettings {
                tempPrompt = newPrompt
            }
        }
        .onChange(of: viewModel.geminiAPIKey) { newAPIKey in
            // Update temp API key when ViewModel changes
            if !showAISettings {
                tempAPIKey = newAPIKey
            }
        }
    }

    private func label(for camera: CameraType) -> String {
        switch camera {
        case .wide: return "Wide 1x"
        case .ultra: return "Ultra Wide 0.5x"
        }
    }
}

#Preview {
    ContentView(viewModel: AppViewModel())
}