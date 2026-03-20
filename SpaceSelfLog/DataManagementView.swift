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
    @State private var sessionInfo: (sessionId: String, sessionStartTime: Date, analysisCount: Int, totalImageSize: String, totalDataSize: String, analysisInterval: TimeInterval) = ("", Date(), 0, "0 MB", "0 MB", 10.0)
    @State private var historicalSessions: [SessionInfo] = []
    @State private var showingDeleteAlert = false
    @State private var sessionToDelete: SessionInfo?
    @State private var isDeleting = false
    @State private var isAverageDataExpanded = false
    
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
                        Text("Analysis Count")
                        Spacer()
                        Text("\(sessionInfo.analysisCount)")
                            .foregroundColor(.secondary)
                    }
                    
                    HStack {
                        Text("Total Image Size")
                        Spacer()
                        Text(sessionInfo.totalImageSize)
                            .foregroundColor(.secondary)
                    }
                    
                    HStack {
                        Text("Total Data Size")
                        Spacer()
                        Text(sessionInfo.totalDataSize)
                            .foregroundColor(.secondary)
                    }
                    
                    // Average data size section
                    Button(action: {
                        withAnimation(.easeInOut(duration: 0.3)) {
                            isAverageDataExpanded.toggle()
                        }
                    }) {
                        HStack {
                            Text("Avg. Data Size Per Entry")
                            Spacer()
                            Text(getAverageDataSizePerEntry())
                                .foregroundColor(.secondary)
                            Image(systemName: isAverageDataExpanded ? "chevron.up" : "chevron.down")
                                .foregroundColor(.secondary)
                                .font(.caption)
                        }
                    }
                    .buttonStyle(PlainButtonStyle())
                    
                    if isAverageDataExpanded {
                        HStack {
                            Text("Avg. Data Size Per Min")
                                .padding(.leading, 16)
                            Spacer()
                            Text(getAverageDataSizePerMinute())
                                .foregroundColor(.secondary)
                        }
                        .transition(.opacity.combined(with: .move(edge: .top)))
                        
                        HStack {
                            Text("Avg. Data Size Per Hour")
                                .padding(.leading, 16)
                            Spacer()
                            Text(getAverageDataSizePerHour())
                                .foregroundColor(.secondary)
                        }
                        .transition(.opacity.combined(with: .move(edge: .top)))
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
                                    VStack(alignment: .leading, spacing: 2) {
                                        Text(session.formattedStartTime)
                                            // .font(.headline)
                                    }
                                    
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
                                        Image(systemName: "doc.text")
                                        Text("\(session.recordCount)")
                                    }
                                    .font(.caption)
                                    .foregroundColor(.secondary)
                                    
                                    HStack(spacing: 4) {
                                        Image(systemName: "photo")
                                        Text("\(session.imageCount)")
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
                    .disabled(isClearing || sessionInfo.analysisCount == 0)
                }
                
                // Description section
                Section("Description") {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("• Current session data is stored in separate folders")
                            .font(.caption)
                            .foregroundColor(.secondary)
                        Text("• New session is created each time app starts")
                            .font(.caption)
                            .foregroundColor(.secondary)
                        Text("• Historical sessions are sorted by time, can view and delete")
                            .font(.caption)
                            .foregroundColor(.secondary)
                        Text("• Clear data will delete all analysis records and images")
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
                Text("This will delete all analysis data and images from current session and cannot be undone. Continue?")
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
        
        viewModel.deleteHistoricalSession(sessionId: session.sessionId) { [self] success in
            isDeleting = false
            sessionToDelete = nil
            
            if success {
                // Refresh historical sessions list
                updateHistoricalSessions()
            } else {
                // Can display error message here
                print("Failed to delete session")
            }
        }
    }
    
    // MARK: - Average data size calculation methods
    
    private func getAverageDataSizePerEntry() -> String {
        guard sessionInfo.analysisCount > 0 else { return "0 B" }
        
        // From string extract bytes
        let totalBytes = extractBytesFromSizeString(sessionInfo.totalDataSize)
        let averageBytes = totalBytes / Int64(sessionInfo.analysisCount)
        
        let formatter = ByteCountFormatter()
        formatter.allowedUnits = [.useBytes, .useKB, .useMB, .useGB]
        formatter.countStyle = .file
        
        return formatter.string(fromByteCount: averageBytes)
    }
    
    private func getAverageDataSizePerMinute() -> String {
        guard sessionInfo.analysisCount > 0 else { return "0 B" }
        
        let totalBytes = extractBytesFromSizeString(sessionInfo.totalDataSize)
        let averageBytesPerEntry = totalBytes / Int64(sessionInfo.analysisCount)
        let entriesPerMinute = 60.0 / sessionInfo.analysisInterval
        let averageBytesPerMinute = Int64(Double(averageBytesPerEntry) * entriesPerMinute)
        
        let formatter = ByteCountFormatter()
        formatter.allowedUnits = [.useBytes, .useKB, .useMB, .useGB]
        formatter.countStyle = .file
        
        return formatter.string(fromByteCount: averageBytesPerMinute)
    }
    
    private func getAverageDataSizePerHour() -> String {
        guard sessionInfo.analysisCount > 0 else { return "0 B" }
        
        let totalBytes = extractBytesFromSizeString(sessionInfo.totalDataSize)
        let averageBytesPerEntry = totalBytes / Int64(sessionInfo.analysisCount)
        let entriesPerMinute = 60.0 / sessionInfo.analysisInterval
        let averageBytesPerHour = Int64(Double(averageBytesPerEntry) * entriesPerMinute * 60.0)
        
        let formatter = ByteCountFormatter()
        formatter.allowedUnits = [.useBytes, .useKB, .useMB, .useGB]
        formatter.countStyle = .file
        
        return formatter.string(fromByteCount: averageBytesPerHour)
    }
    
    private func extractBytesFromSizeString(_ sizeString: String) -> Int64 {
        // Simple byte extraction logic, extract value from formatted string
        let components = sizeString.components(separatedBy: " ")
        guard components.count >= 2,
              let value = Double(components[0]) else { return 0 }
        
        let unit = components[1].uppercased()
        switch unit {
        case "B", "BYTES":
            return Int64(value)
        case "KB":
            return Int64(value * 1024)
        case "MB":
            return Int64(value * 1024 * 1024)
        case "GB":
            return Int64(value * 1024 * 1024 * 1024)
        default:
            return 0
        }
    }
    
    private func clearAllData() {
        isClearing = true
        viewModel.clearAllAnalysisData { result in
            isClearing = false
            switch result {
            case .success:
                clearMessage = "All data from current session has been successfully cleared"
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