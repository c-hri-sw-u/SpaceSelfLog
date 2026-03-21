import SwiftUI

extension DateFormatter {
    static let sessionTime: DateFormatter = {
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd HH:mm:ss"
        return formatter
    }()
}

struct DataManagementView: View {
    @ObservedObject var viewModel: AppViewModel
    @State private var showingClearAlert = false
    @State private var clearMessage = ""
    @State private var showingClearResult = false
    @State private var isClearing = false
    @State private var sessionInfo: (sessionId: String, sessionStartTime: Date, frameCount: Int, totalFrameSize: String, totalDataSize: String) = ("", Date(), 0, "0 MB", "0 MB")
    @State private var historicalSessions: [SessionInfo] = []
    @State private var showingDeleteAlert = false
    @State private var sessionToDelete: SessionInfo?
    @State private var isDeleting = false

    var body: some View {
        NavigationView {
            List {
                // Current session info section
                Section("Current Session") {
                    HStack {
                        Text("Session ID")
                        Spacer()
                        Text(sessionInfo.sessionId)
                            .foregroundColor(.secondary)
                            .font(.caption)
                    }

                    HStack {
                        Text("Start Time")
                        Spacer()
                        Text(DateFormatter.sessionTime.string(from: sessionInfo.sessionStartTime))
                            .foregroundColor(.secondary)
                            .font(.caption)
                    }

                    HStack {
                        Text("Frames Captured")
                        Spacer()
                        Text("\(sessionInfo.frameCount)")
                            .foregroundColor(.secondary)
                    }

                    HStack {
                        Text("Total Frame Size")
                        Spacer()
                        Text(sessionInfo.totalFrameSize)
                            .foregroundColor(.secondary)
                    }

                    HStack {
                        Text("Total Data Size")
                        Spacer()
                        Text(sessionInfo.totalDataSize)
                            .foregroundColor(.secondary)
                    }
                }

                // Historical sessions section
                Section("Historical Sessions") {
                    if historicalSessions.isEmpty {
                        HStack {
                            Image(systemName: "clock")
                                .foregroundColor(.secondary)
                            Text("No Historical Sessions")
                                .foregroundColor(.secondary)
                        }
                        .padding(.vertical, 8)
                    } else {
                        ForEach(historicalSessions, id: \.sessionId) { session in
                            VStack(alignment: .leading, spacing: 6) {
                                HStack {
                                    Text(session.formattedStartTime)

                                    Spacer()

                                    if session.isCurrentSession {
                                        Text("Current")
                                            .font(.caption)
                                            .padding(.horizontal, 8)
                                            .padding(.vertical, 2)
                                            .background(Color.blue.opacity(0.2))
                                            .foregroundColor(.blue)
                                            .cornerRadius(4)
                                    } else {
                                        Button(action: {
                                            sessionToDelete = session
                                            showingDeleteAlert = true
                                        }) {
                                            Image(systemName: "trash")
                                                .foregroundColor(.red)
                                        }
                                        .disabled(isDeleting)
                                    }
                                }

                                HStack(spacing: 12) {
                                    HStack(spacing: 4) {
                                        Image(systemName: "photo")
                                        Text("\(session.frameCount) frames")
                                    }
                                    .font(.caption)
                                    .foregroundColor(.secondary)

                                    HStack(spacing: 4) {
                                        Image(systemName: "externaldrive")
                                        Text(session.formattedSize)
                                    }
                                    .font(.caption)
                                    .foregroundColor(.secondary)

                                    Spacer()
                                }
                            }
                            .padding(.vertical, 4)
                        }
                    }
                }

                // Data management section
                Section("Data Management") {
                    Button(action: {
                        showingClearAlert = true
                    }) {
                        HStack {
                            Image(systemName: "trash")
                                .foregroundColor(.red)
                            Text("Clear All Data")
                                .foregroundColor(.red)
                            Spacer()
                            if isClearing {
                                ProgressView()
                                    .scaleEffect(0.8)
                            }
                        }
                    }
                    .disabled(isClearing || sessionInfo.frameCount == 0)
                }

                // Description section
                Section("Description") {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("• Frames are captured at IMU-adaptive intervals (min/max configurable)")
                            .font(.caption)
                            .foregroundColor(.secondary)
                        Text("• New session is created each time recording starts")
                            .font(.caption)
                            .foregroundColor(.secondary)
                        Text("• Historical sessions are sorted by time, can view and delete")
                            .font(.caption)
                            .foregroundColor(.secondary)
                        Text("• Clear data will delete all frames from current session")
                            .font(.caption)
                            .foregroundColor(.secondary)
                    }
                }
            }
            .navigationTitle("Data Management")
            .navigationBarTitleDisplayMode(.inline)
            .onAppear {
                updateSessionInfo()
                updateHistoricalSessions()
            }
            .refreshable {
                updateSessionInfo()
                updateHistoricalSessions()
            }
            .alert("Clear Result", isPresented: $showingClearResult) {
                Button("OK") { }
            } message: {
                Text(clearMessage)
            }
            .alert("Confirm Clear", isPresented: $showingClearAlert) {
                Button("Cancel", role: .cancel) { }
                Button("Clear", role: .destructive) {
                    clearAllData()
                }
            } message: {
                Text("This will delete all frames from the current session and cannot be undone. Continue?")
            }
            .alert("Delete Session", isPresented: $showingDeleteAlert) {
                Button("Cancel", role: .cancel) { }
                Button("Delete", role: .destructive) {
                    deleteHistoricalSession()
                }
            } message: {
                if let session = sessionToDelete {
                    Text("Delete all data for session \(session.formattedStartTime)? This cannot be undone.")
                }
            }
        }
    }

    private func updateSessionInfo() {
        sessionInfo = viewModel.getCurrentSessionInfo()
    }

    private func updateHistoricalSessions() {
        historicalSessions = viewModel.getHistoricalSessions()
    }

    private func deleteHistoricalSession() {
        guard let session = sessionToDelete else { return }
        isDeleting = true
        viewModel.deleteHistoricalSession(sessionId: session.sessionId) { success in
            isDeleting = false
            sessionToDelete = nil
            if success { updateHistoricalSessions() }
        }
    }

    private func clearAllData() {
        isClearing = true
        viewModel.clearSessionData { result in
            isClearing = false
            switch result {
            case .success:
                clearMessage = "All frames from current session have been cleared"
                showingClearResult = true
                updateSessionInfo()
            case .failure(let error):
                clearMessage = "Clear failed: \(error.localizedDescription)"
                showingClearResult = true
            }
        }
    }
}

#Preview {
    DataManagementView(viewModel: AppViewModel())
}
