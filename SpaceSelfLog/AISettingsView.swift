import SwiftUI

struct AISettingsView: View {
    @ObservedObject var viewModel: AppViewModel
    @Binding var tempAPIKey: String
    @Binding var tempPrompt: String
    @Binding var tempInterval: Double
    @Binding var isTestingAPIKey: Bool
    
    @Environment(\.presentationMode) var presentationMode
    @State private var apiKeyTestResult: String?
    @State private var showingAPIKeyTest = false
    @State private var showingDataManagement = false
    @State private var tempUsingOpenRouter: Bool = false
    @State private var tempOpenRouterAPIKey: String = ""
    @State private var tempExperimentNumber: Int = 1
    
    var body: some View {
        NavigationView {
            Form {
                Section(header: Text("AI Provider")) {
                    VStack(alignment: .leading, spacing: 8) {
                        Toggle("Use OpenRouter Preset (@preset/space-self-log)", isOn: $tempUsingOpenRouter)
                        Text(tempUsingOpenRouter ? "OpenRouter is active" : "Gemini is active")
                            .font(.caption)
                            .foregroundColor(.gray)
                    }
                }

                Section(header: Text("API Key Config")) {
                    VStack(alignment: .leading, spacing: 8) {
                        if tempUsingOpenRouter {
                            Text("OpenRouter API Key")
                                .font(.headline)
                            SecureField("Enter your OpenRouter API Key", text: $tempOpenRouterAPIKey)
                                .textFieldStyle(RoundedBorderTextFieldStyle())
                            Text("Preset: @preset/space-self-log")
                                .font(.caption)
                                .foregroundColor(.gray)
                        } else {
                            Text("Gemini API Key")
                                .font(.headline)
                            SecureField("Enter your Gemini API Key", text: $tempAPIKey)
                                .textFieldStyle(RoundedBorderTextFieldStyle())
                        }

                        HStack {
                            Button("Test API Key") {
                                testAPIKey()
                            }
                            .disabled((tempUsingOpenRouter ? tempOpenRouterAPIKey.isEmpty : tempAPIKey.isEmpty) || isTestingAPIKey)

                            if isTestingAPIKey {
                                ProgressView()
                                    .scaleEffect(0.8)
                            }

                            Spacer()
                        }

                        if let result = apiKeyTestResult {
                            Text(result)
                                .font(.caption)
                                .foregroundColor(result.contains("successful") || result.contains("Success") ? .green : .red)
                        }
                    }
                }
                
                Section(header: Text("Analysis Config")) {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Analysis Prompt")
                            .font(.headline)
                        TextEditor(text: $tempPrompt)
                            .frame(minHeight: 80)
                            .overlay(
                                RoundedRectangle(cornerRadius: 8)
                                    .stroke(Color.gray.opacity(0.3), lineWidth: 1)
                            )
                    }
                    
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Analysis Interval: \(Int(tempInterval))s")
                            .font(.headline)
                        Slider(value: $tempInterval, in: 10...300, step: 5)
                        HStack {
                            Text("10s")
                                .font(.caption)
                                .foregroundColor(.gray)
                            Spacer()
                            Text("5min")
                                .font(.caption)
                                .foregroundColor(.gray)
                        }
                    }
                    
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Experiment")
                            .font(.headline)
                        Picker("Experiment", selection: $tempExperimentNumber) {
                            ForEach(ExperimentRegistry.ids, id: \.self) { id in
                                Text("\(id)").tag(id)
                            }
                        }
                        .pickerStyle(SegmentedPickerStyle())
                    }
                }
                
                Section(header: Text("Current Status")) {
                    HStack {
                        Text("Analysis Status")
                        Spacer()
                        Text(viewModel.isAIAnalysisEnabled ? "Running" : "Stopped")
                            .foregroundColor(viewModel.isAIAnalysisEnabled ? .green : .gray)
                    }
                    
                    if let result = viewModel.latestAnalysisResult {
                        VStack(alignment: .leading, spacing: 4) {
                            Text("Latest Result")
                                .font(.headline)
                            Text("Formatted Output: \(result.formattedOutput.activityLabel)")
                            Text("Raw Output: \(result.modelOutput)")
                                .font(.caption)
                                .foregroundColor(.gray)
                            Text("Time: \(DateFormatter.shortTime.string(from: result.captureTime))")
                                .font(.caption)
                                .foregroundColor(.gray)
                        }
                    }
                    
                    HStack {
                        Text("History Records")
                        Spacer()
                        Text("\(viewModel.analysisHistory.count) items")
                            .foregroundColor(.gray)
                    }
                }
                
                Section(header: Text("Data Management")) {
                    Button(action: {
                        showingDataManagement = true
                    }) {
                        HStack {
                            Image(systemName: "folder")
                                .foregroundColor(.blue)
                            Text("Manage Analysis Data")
                            Spacer()
                            Image(systemName: "chevron.right")
                                .font(.caption)
                                .foregroundColor(.gray)
                        }
                    }
                    .foregroundColor(.primary)
                }
            }
            .navigationTitle("AI Analysis Settings")
            .navigationBarTitleDisplayMode(.inline)
            .navigationBarItems(
                leading: Button("Cancel") {
                    presentationMode.wrappedValue.dismiss()
                },
                trailing: HStack {
                    Button("Refresh") {
                        refreshSettings()
                    }
                    Button("Save") {
                        saveSettings()
                    }
                }
            )
            .onAppear {
                // Refresh temp values when settings view appears
                // This ensures we show the latest values even if they were changed from web interface
                tempUsingOpenRouter = viewModel.usingOpenRouter
                tempOpenRouterAPIKey = viewModel.openRouterAPIKey
                tempAPIKey = viewModel.geminiAPIKey
                tempPrompt = viewModel.aiAnalysisPrompt
                tempInterval = viewModel.aiAnalysisInterval
                tempExperimentNumber = viewModel.experimentNumber
            }
            .sheet(isPresented: $showingDataManagement) {
                DataManagementView(viewModel: viewModel)
            }
        }
    }
    
    private func testAPIKey() {
        isTestingAPIKey = true
        apiKeyTestResult = nil

        if tempUsingOpenRouter {
            guard !tempOpenRouterAPIKey.isEmpty else { isTestingAPIKey = false; return }
            viewModel.testOpenRouterAPIKey(tempOpenRouterAPIKey) { success, error in
                isTestingAPIKey = false
                if success {
                    apiKeyTestResult = "API Key test successful!"
                } else {
                    apiKeyTestResult = "API Key test failed: \(error ?? "Unknown error")"
                }
            }
        } else {
            guard !tempAPIKey.isEmpty else { isTestingAPIKey = false; return }
            viewModel.testGeminiAPIKey(tempAPIKey) { success, error in
                isTestingAPIKey = false
                if success {
                    apiKeyTestResult = "API Key test successful!"
                } else {
                    apiKeyTestResult = "API Key test failed: \(error ?? "Unknown error")"
                }
            }
        }
    }
    
    private func refreshSettings() {
        // Manually refresh temp values from ViewModel
        tempUsingOpenRouter = viewModel.usingOpenRouter
        tempOpenRouterAPIKey = viewModel.openRouterAPIKey
        tempAPIKey = viewModel.geminiAPIKey
        tempPrompt = viewModel.aiAnalysisPrompt
        tempInterval = viewModel.aiAnalysisInterval
        tempExperimentNumber = viewModel.experimentNumber
    }
    
    private func saveSettings() {
        viewModel.usingOpenRouter = tempUsingOpenRouter
        viewModel.openRouterAPIKey = tempOpenRouterAPIKey
        viewModel.geminiAPIKey = tempAPIKey
        viewModel.updateAIAnalysisPrompt(tempPrompt)
        viewModel.updateAIAnalysisInterval(tempInterval)
        viewModel.updateExperiment(tempExperimentNumber)
        presentationMode.wrappedValue.dismiss()
    }
}

#Preview {
    AISettingsView(
        viewModel: AppViewModel(),
        tempAPIKey: .constant(""),
        tempPrompt: .constant("What do you see in this image? Respond with a single English word in lowercase."),
        tempInterval: .constant(30.0),
        isTestingAPIKey: .constant(false)
    )
}
