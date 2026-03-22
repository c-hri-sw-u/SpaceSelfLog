import SwiftUI

struct ExperimentSettingsView: View {
    @ObservedObject var viewModel: AppViewModel
    @Environment(\.presentationMode) var presentationMode

    // Capture
    @State private var tempMinInterval: Int = 3
    @State private var tempMaxInterval: Int = 20
    @State private var tempRampRatio: Double = 1.67

    // Audio
    @State private var tempVADSensitivity: String = "Med"
    @State private var tempTranscriptionEnabled: Bool = false

    // IMU
    @State private var tempSustainedMotionThreshold: Int = 6

    // Batch
    @State private var tempBatchMaxWindow: Int = 600
    @State private var tempBatchMaxWindowMin: Int = 10
    @State private var tempSSIMThreshold: Double = 0.75
    @State private var tempSSIMDedupThreshold: Double = 0.92
    @State private var tempKDensityPerMin: Double = 1.0
    @State private var tempKMin: Int = 2
    @State private var tempKMax: Int = 12
    @State private var tempScoreThreshold: Double = 0.50

    // Outbox
    @State private var tempOutboxEndpoint: String = ""
    @State private var liveOutboxQueueSize: Int = 0
    @State private var liveOutboxStatus: String = "idle"
    @State private var liveOutboxFailures: Int = 0

    @State private var showingDataManagement = false

    var body: some View {
        NavigationView {
            Form {
                // MARK: Capture
                Section(header: Text("Capture")) {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Min Interval (s): \(tempMinInterval)")
                        Stepper("", value: $tempMinInterval, in: 1...30)
                            .labelsHidden()
                    }
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Max Interval (s): \(tempMaxInterval)")
                        Stepper("", value: $tempMaxInterval, in: 5...120)
                            .labelsHidden()
                    }
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Ramp-up Speed")
                        Picker("Ramp-up Speed", selection: $tempRampRatio) {
                            Text("Slow (×1.3)").tag(1.3)
                            Text("Med (×1.67)").tag(1.67)
                            Text("Fast (×2.0)").tag(2.0)
                        }
                        .pickerStyle(SegmentedPickerStyle())
                    }
                }

                // MARK: Audio
                Section(header: Text("Audio")) {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("VAD Sensitivity")
                        Picker("VAD Sensitivity", selection: $tempVADSensitivity) {
                            Text("Low").tag("Low")
                            Text("Med").tag("Med")
                            Text("High").tag("High")
                        }
                        .pickerStyle(SegmentedPickerStyle())
                    }
                    Toggle("Transcription", isOn: $tempTranscriptionEnabled)
                }

                // MARK: IMU
                Section(header: Text("IMU")) {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Sustained Motion Threshold (s): \(tempSustainedMotionThreshold)")
                        Stepper("", value: $tempSustainedMotionThreshold, in: 1...30)
                            .labelsHidden()
                    }
                }

                // MARK: Batch
                Section(header: Text("Batch (Layer 1.5)")) {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Max Window (min): \(tempBatchMaxWindowMin)")
                        Stepper("", value: $tempBatchMaxWindowMin, in: 1...120)
                            .labelsHidden()
                    }

                    VStack(alignment: .leading, spacing: 6) {
                        Text(String(format: "Scene SSIM: %.2f", tempSSIMThreshold))
                        Slider(value: $tempSSIMThreshold, in: 0.50...0.95, step: 0.01)
                        HStack {
                            Text("0.50  more cuts").font(.caption2).foregroundColor(.secondary)
                            Spacer()
                            Text("fewer cuts  0.95").font(.caption2).foregroundColor(.secondary)
                        }
                    }

                    VStack(alignment: .leading, spacing: 6) {
                        Text(String(format: "Dedup SSIM: %.2f", tempSSIMDedupThreshold))
                        Slider(value: $tempSSIMDedupThreshold, in: 0.80...1.00, step: 0.01)
                        HStack {
                            Text("0.80  more unique").font(.caption2).foregroundColor(.secondary)
                            Spacer()
                            Text("keep dupes  1.00").font(.caption2).foregroundColor(.secondary)
                        }
                    }

                    VStack(alignment: .leading, spacing: 6) {
                        Text(String(format: "K density: %.1f frames/min", tempKDensityPerMin))
                        Slider(value: $tempKDensityPerMin, in: 0.5...3.0, step: 0.5)
                        HStack {
                            Text("0.5").font(.caption2).foregroundColor(.secondary)
                            Spacer()
                            Text("3.0 frames/min").font(.caption2).foregroundColor(.secondary)
                        }
                    }
                    HStack(spacing: 16) {
                        VStack(alignment: .leading, spacing: 8) {
                            Text("K min: \(tempKMin)")
                            Stepper("", value: $tempKMin, in: 1...tempKMax)
                                .labelsHidden()
                        }
                        VStack(alignment: .leading, spacing: 8) {
                            Text("K max: \(tempKMax)")
                            Stepper("", value: $tempKMax, in: tempKMin...30)
                                .labelsHidden()
                        }
                    }
                    VStack(alignment: .leading, spacing: 6) {
                        Text(String(format: "Score threshold: %.2f", tempScoreThreshold))
                        Slider(value: $tempScoreThreshold, in: 0.30...0.80, step: 0.05)
                        HStack {
                            Text("0.30  more frames").font(.caption2).foregroundColor(.secondary)
                            Spacer()
                            Text("fewer  0.80").font(.caption2).foregroundColor(.secondary)
                        }
                    }
                }

                // MARK: Outbox
                Section(header: Text("Outbox / Upload")) {
                    VStack(alignment: .leading, spacing: 6) {
                        Text("Upload endpoint")
                            .font(.caption)
                            .foregroundColor(.secondary)
                        TextField("http://100.x.x.x:8000/ingest", text: $tempOutboxEndpoint)
                            .autocapitalization(.none)
                            .disableAutocorrection(true)
                            .keyboardType(.URL)
                    }

                    HStack {
                        Image(systemName: outboxStatusIcon)
                            .foregroundColor(outboxStatusColor)
                            .frame(width: 16)
                        Text(liveOutboxStatus == "idle" ? "No upload configured" : liveOutboxStatus)
                            .font(.caption)
                            .foregroundColor(.secondary)
                            .lineLimit(1)
                            .truncationMode(.tail)
                        Spacer()
                        if liveOutboxQueueSize > 0 {
                            Text("\(liveOutboxQueueSize) queued")
                                .font(.caption)
                                .foregroundColor(.orange)
                        }
                    }
                    if liveOutboxFailures > 0 {
                        Text("\(liveOutboxFailures) upload failure(s)")
                            .font(.caption2)
                            .foregroundColor(.red)
                    }
                }

                // MARK: Data Management
                Section(header: Text("Data Management")) {
                    Button(action: { showingDataManagement = true }) {
                        HStack {
                            Image(systemName: "folder")
                                .foregroundColor(.blue)
                            Text("Manage Capture Data")
                            Spacer()
                            Image(systemName: "chevron.right")
                                .font(.caption)
                                .foregroundColor(.secondary)
                        }
                    }
                    .foregroundColor(.primary)
                }
            }
            .navigationTitle("Experiment Settings")
            .navigationBarTitleDisplayMode(.inline)
            .navigationBarItems(
                leading: Button("Cancel") {
                    presentationMode.wrappedValue.dismiss()
                },
                trailing: Button("Save") {
                    saveSettings()
                }
            )
            .onAppear { loadSettings() }
            .sheet(isPresented: $showingDataManagement) {
                DataManagementView(viewModel: viewModel)
            }
        }
    }

    // MARK: - Outbox status helpers

    private var outboxStatusIcon: String {
        switch liveOutboxStatus {
        case "ok":   return "checkmark.circle"
        case "idle": return "circle.dotted"
        default:     return "exclamationmark.circle"
        }
    }

    private var outboxStatusColor: Color {
        switch liveOutboxStatus {
        case "ok":   return .green
        case "idle": return .secondary
        default:     return .orange
        }
    }

    // MARK: - Load / Save

    private func loadSettings() {
        tempMinInterval               = viewModel.captureMinInterval
        tempMaxInterval               = viewModel.captureMaxInterval
        tempRampRatio                 = viewModel.rampRatio
        tempVADSensitivity            = viewModel.vadSensitivity
        tempTranscriptionEnabled      = viewModel.transcriptionEnabled
        tempSustainedMotionThreshold  = viewModel.sustainedMotionThreshold
        tempBatchMaxWindow            = viewModel.batchMaxWindow
        tempBatchMaxWindowMin         = max(1, viewModel.batchMaxWindow / 60)
        tempSSIMThreshold             = viewModel.ssimThreshold
        tempSSIMDedupThreshold        = viewModel.ssimDedupThreshold
        tempKDensityPerMin            = viewModel.kDensityPerMin
        tempKMin                      = viewModel.kMin
        tempKMax                      = viewModel.kMax
        tempScoreThreshold            = viewModel.scoreThreshold
        tempOutboxEndpoint            = viewModel.outboxEndpoint
        liveOutboxQueueSize           = viewModel.outboxQueueSize
        liveOutboxStatus              = viewModel.outboxUploadStatus
        liveOutboxFailures            = viewModel.outboxFailureCount
    }

    private func saveSettings() {
        viewModel.captureMinInterval        = tempMinInterval
        viewModel.captureMaxInterval        = tempMaxInterval
        viewModel.rampRatio                 = tempRampRatio
        viewModel.vadSensitivity            = tempVADSensitivity
        viewModel.transcriptionEnabled      = tempTranscriptionEnabled
        viewModel.sustainedMotionThreshold  = tempSustainedMotionThreshold
        viewModel.batchMaxWindow            = tempBatchMaxWindowMin * 60
        viewModel.ssimThreshold             = tempSSIMThreshold
        viewModel.ssimDedupThreshold        = tempSSIMDedupThreshold
        viewModel.kDensityPerMin            = tempKDensityPerMin
        viewModel.kMin                      = tempKMin
        viewModel.kMax                      = tempKMax
        viewModel.scoreThreshold            = tempScoreThreshold
        viewModel.outboxEndpoint            = tempOutboxEndpoint
        presentationMode.wrappedValue.dismiss()
    }
}

#Preview {
    ExperimentSettingsView(viewModel: AppViewModel())
}
