import Foundation
import Network

final class StreamServer {
    let port: UInt16
    private var listener: NWListener?
    private let queue = DispatchQueue(label: "StreamServer.listener")
    private var clients: [NWConnection] = []
    private var streamingClients: Set<ObjectIdentifier> = []
    
    var isRunning: Bool { listener != nil }
    
    // Control callbacks
    var onStart: (() -> Void)?
    var onStop: (() -> Void)?
    var onPause: (() -> Void)?
    var onResume: (() -> Void)?
    var onSwitch: ((CameraType) -> Void)?
    var onRotate: (() -> Void)?
    var onResolution: ((ResolutionPreset) -> Void)?
    var onStatus: (() -> [String: Any])?
    var onTestAPIKey: (() -> (success: Bool, error: String?))?
    var onUpdateCaptureConfig: ((_ minInterval: Int, _ maxInterval: Int, _ rampRatio: Double) -> Bool)?
    var onUpdateAudioConfig: ((_ vadSensitivity: String, _ transcriptionEnabled: Bool, _ noiseQuietDB: Int, _ noiseLoudDB: Int) -> Bool)?
    var onUpdateIMUConfig: ((_ sustainedMotionThreshold: Int, _ varianceLow: Double, _ varianceHigh: Double) -> Bool)?
    var onUpdateBatchConfig: ((_ firstBatchWindow: Int, _ maxWindow: Int, _ ssimThreshold: Double, _ ssimDedupThreshold: Double, _ kDensityPerMin: Double, _ kMin: Int, _ kMax: Int, _ scoreThreshold: Double, _ batchMaxOutput: Int) -> Bool)?
    var onUpdateOutboxConfig: ((_ endpoint: String) -> Bool)?
    
    init(port: UInt16 = 8080) {
        self.port = port
    }
    
    func start() {
        guard listener == nil else { return }
        do {
            let params = NWParameters.tcp
            let l = try NWListener(using: params, on: NWEndpoint.Port(rawValue: port)!)
            listener = l
            l.newConnectionHandler = { [weak self] connection in
                self?.handle(connection: connection)
            }
            l.start(queue: queue)
        } catch {
            print("StreamServer start error: \(error)")
        }
    }
    
    func stop() {
        listener?.cancel()
        listener = nil
        queue.async { [weak self] in
            self?.clients.forEach { $0.cancel() }
            self?.clients.removeAll()
            self?.streamingClients.removeAll()
        }
    }
    
    // Broadcast a single JPEG frame to all /stream clients
    func broadcastJPEGFrame(_ data: Data) {
        let header = "\r\n--frame\r\nContent-Type: image/jpeg\r\nContent-Length: \(data.count)\r\n\r\n"
        let tail = "\r\n"
        
        queue.async { [weak self] in
            guard let self = self else { return }
            for conn in self.clients {
                let id = ObjectIdentifier(conn)
                guard self.streamingClients.contains(id) else { continue }
                conn.send(content: header.data(using: .utf8), completion: .contentProcessed { _ in })
                conn.send(content: data, completion: .contentProcessed { _ in })
                conn.send(content: tail.data(using: .utf8), completion: .contentProcessed { _ in })
            }
        }
    }
    
    // MARK: - Connection Handling
    private func handle(connection: NWConnection) {
        clients.append(connection)
        connection.stateUpdateHandler = { [weak self] state in
            switch state {
            case .ready:
                self?.receiveRequest(on: connection)
            case .failed(let error):
                print("Conn failed: \(error)")
                self?.cleanup(connection)
            case .cancelled:
                self?.cleanup(connection)
            default:
                break
            }
        }
        connection.start(queue: queue)
    }
    
    private func cleanup(_ connection: NWConnection) {
        let id = ObjectIdentifier(connection)
        streamingClients.remove(id)
        clients.removeAll { ObjectIdentifier($0) == id }
    }
    
    private func receiveRequest(on connection: NWConnection) {
        readUntilHeadersEnd(on: connection) { [weak self] request, leftoverBody in
            guard let self = self else { return }
            let path = self.parsePath(from: request)
            switch path.route {
            case "/stream":
                self.streamingHandshake(connection)
            case "/start":
                self.onStart?()
                self.simpleOK(connection, body: "started")
            case "/stop":
                self.onStop?()
                self.simpleOK(connection, body: "stopped")
            case "/pause":
                self.onPause?()
                self.simpleOK(connection, body: "paused")
            case "/resume":
                self.onResume?()
                self.simpleOK(connection, body: "resumed")
            case "/switch":
                if let camStr = path.query["camera"], let cam = CameraType(rawValue: camStr) {
                    self.onSwitch?(cam)
                    self.simpleOK(connection, body: "switched:\(camStr)")
                } else {
                    self.simpleBadRequest(connection, body: "missing camera")
                }
            case "/rotate":
                self.onRotate?()
                self.simpleOK(connection, body: "rotated")
            case "/resolution":
                if let resStr = path.query["preset"], let resolution = ResolutionPreset(rawValue: resStr) {
                    self.onResolution?(resolution)
                    self.simpleOK(connection, body: "resolution:\(resStr)")
                } else {
                    self.simpleBadRequest(connection, body: "missing preset")
                }
            case "/status":
                let dict = self.onStatus?() ?? [:]
                let data = try? JSONSerialization.data(withJSONObject: dict, options: [])
                self.simpleOK(connection, contentType: "application/json", bodyData: data)
            case "/test-api-key":
                let result = self.onTestAPIKey?() ?? (success: false, error: "Not implemented")
                let responseData: [String: Any] = ["success": result.success, "error": result.error ?? ""]
                let data = try? JSONSerialization.data(withJSONObject: responseData, options: [])
                self.simpleOK(connection, contentType: "application/json", bodyData: data)
            case "/update-capture-config":
                self.handleJSONPost(connection, leftover: leftoverBody, request: request) { [weak self] json in
                    let minInterval = json["minInterval"] as? Int    ?? 3
                    let maxInterval = json["maxInterval"] as? Int    ?? 20
                    let rampRatio   = json["rampRatio"]   as? Double ?? 1.67
                    let success = self?.onUpdateCaptureConfig?(minInterval, maxInterval, rampRatio) ?? false
                    return (success, success ? nil : "Not implemented")
                }
            case "/update-audio-config":
                self.handleJSONPost(connection, leftover: leftoverBody, request: request) { [weak self] json in
                    let vadSensitivity       = json["vadSensitivity"]       as? String ?? "medium"
                    let transcriptionEnabled = json["transcriptionEnabled"] as? Bool   ?? false
                    let noiseQuietDB         = json["noiseQuietDB"]         as? Int    ?? -50
                    let noiseLoudDB          = json["noiseLoudDB"]          as? Int    ?? -30
                    let success = self?.onUpdateAudioConfig?(vadSensitivity, transcriptionEnabled, noiseQuietDB, noiseLoudDB) ?? false
                    return (success, success ? nil : "Not implemented")
                }
            case "/update-imu-config":
                self.handleJSONPost(connection, leftover: leftoverBody, request: request) { [weak self] json in
                    let threshold     = json["sustainedMotionThreshold"] as? Int    ?? 6
                    let varianceLow   = json["varianceLow"]              as? Double ?? 0.006
                    let varianceHigh  = json["varianceHigh"]             as? Double ?? 0.012
                    let success = self?.onUpdateIMUConfig?(threshold, varianceLow, varianceHigh) ?? false
                    return (success, success ? nil : "Not implemented")
                }
            case "/update-batch-config":
                self.handleJSONPost(connection, leftover: leftoverBody, request: request) { [weak self] json in
                    let firstBatchWindow   = json["firstBatchWindow"]   as? Int    ?? 120
                    let maxWindow          = json["maxWindow"]          as? Int    ?? 600
                    let ssimThreshold      = json["ssimThreshold"]      as? Double ?? 0.85
                    let ssimDedupThreshold = json["ssimDedupThreshold"] as? Double ?? 0.92
                    let kDensityPerMin     = json["kDensityPerMin"]     as? Double ?? 1.0
                    let kMin               = json["kMin"]               as? Int    ?? 2
                    let kMax               = json["kMax"]               as? Int    ?? 12
                    let scoreThreshold     = json["scoreThreshold"]     as? Double ?? 0.50
                    let batchMaxOutput     = json["batchMaxOutput"]     as? Int    ?? 20
                    let success = self?.onUpdateBatchConfig?(firstBatchWindow, maxWindow, ssimThreshold, ssimDedupThreshold, kDensityPerMin, kMin, kMax, scoreThreshold, batchMaxOutput) ?? false
                    return (success, success ? nil : "Not implemented")
                }
            case "/update-outbox-config":
                self.handleJSONPost(connection, leftover: leftoverBody, request: request) { [weak self] json in
                    let endpoint = json["endpoint"] as? String ?? ""
                    let success = self?.onUpdateOutboxConfig?(endpoint) ?? false
                    return (success, success ? nil : "Not implemented")
                }
            case "/":
                let html = self.indexHTML()
                self.simpleOK(connection, contentType: "text/html; charset=utf-8", body: html)
            default:
                self.simpleNotFound(connection)
            }
        }
    }
    
    private func streamingHandshake(_ connection: NWConnection) {
        let id = ObjectIdentifier(connection)
        streamingClients.insert(id)
        let headers = [
            "HTTP/1.1 200 OK",
            "Cache-Control: no-cache, no-store, must-revalidate",
            "Pragma: no-cache",
            "Connection: close",
            "Content-Type: multipart/x-mixed-replace; boundary=frame",
            "\r\n"
        ].joined(separator: "\r\n")
        connection.send(content: headers.data(using: .utf8), completion: .contentProcessed { _ in })
        // Keep reading to hold the connection open (optional)
        connection.receive(minimumIncompleteLength: 1, maximumLength: 1_024) { [weak self] _, _, isComplete, _ in
            if isComplete { self?.cleanup(connection) }
        }
    }
    
    // MARK: - Request Parsing
    private func readUntilHeadersEnd(on connection: NWConnection, completion: @escaping (String, Data) -> Void) {
        var buffer = Data()
        let delimiter = "\r\n\r\n".data(using: .utf8)!
        func readMore() {
            connection.receive(minimumIncompleteLength: 1, maximumLength: 4_096) { (data, _, isComplete, error) in
                if let data = data { buffer.append(data) }
                if let range = buffer.range(of: delimiter) {
                    let headerData = buffer.subdata(in: 0..<range.lowerBound)
                    let leftoverBody = buffer.subdata(in: range.upperBound..<buffer.count)
                    let str = String(data: headerData, encoding: .utf8) ?? ""
                    completion(str, leftoverBody)
                } else if isComplete || error != nil {
                    let str = String(data: buffer, encoding: .utf8) ?? ""
                    // 没找到分隔符但连接已结束，传递全部作为头部，其余为空
                    completion(str, Data())
                } else {
                    readMore()
                }
            }
        }
        readMore()
    }
    
    private func parsePath(from request: String) -> (route: String, query: [String: String]) {
        // Expect first line: GET /path?x=y HTTP/1.1
        let firstLine = request.split(separator: "\n").first ?? ""
        let parts = firstLine.split(separator: " ")
        guard parts.count >= 2 else { return ("/", [:]) }
        let urlPart = String(parts[1])
        let comps = urlPart.split(separator: "?", maxSplits: 1, omittingEmptySubsequences: false)
        let route = String(comps.first ?? "/")
        var query: [String: String] = [:]
        if comps.count > 1 {
            for pair in comps[1].split(separator: "&") {
                let kv = pair.split(separator: "=", maxSplits: 1)
                if kv.count == 2 {
                    query[String(kv[0])] = String(kv[1])
                }
            }
        }
        return (route, query)
    }
    
    // Parse Content-Length header (if present)
    private func parseContentLength(from request: String) -> Int? {
        for line in request.split(separator: "\r\n") {
            let lower = line.lowercased()
            if lower.hasPrefix("content-length:") {
                let parts = lower.split(separator: ":", maxSplits: 1)
                if parts.count == 2 {
                    let valueStr = parts[1].trimmingCharacters(in: .whitespaces)
                    return Int(valueStr)
                }
            }
        }
        return nil
    }
    
    // MARK: - Responses
    private func simpleOK(_ conn: NWConnection, contentType: String = "text/plain; charset=utf-8", body: String) {
        simpleOK(conn, contentType: contentType, bodyData: body.data(using: .utf8))
    }
    
    private func simpleOK(_ conn: NWConnection, contentType: String = "text/plain; charset=utf-8", bodyData: Data?) {
        let data = bodyData ?? Data()
        let headers = [
            "HTTP/1.1 200 OK",
            "Content-Type: \(contentType)",
            "Content-Length: \(data.count)",
            "Connection: close",
            "\r\n"
        ].joined(separator: "\r\n")
        conn.send(content: headers.data(using: .utf8), completion: .contentProcessed { _ in })
        conn.send(content: data, completion: .contentProcessed { _ in conn.cancel() })
    }
    
    private func simpleNotFound(_ conn: NWConnection) {
        simpleOK(conn, body: "404 not found")
    }
    
    private func simpleBadRequest(_ conn: NWConnection, body: String) {
        let data = body.data(using: .utf8) ?? Data()
        let headers = [
            "HTTP/1.1 400 Bad Request",
            "Content-Type: text/plain; charset=utf-8",
            "Content-Length: \(data.count)",
            "Connection: close",
            "\r\n"
        ].joined(separator: "\r\n")
        conn.send(content: headers.data(using: .utf8), completion: .contentProcessed { _ in })
        conn.send(content: data, completion: .contentProcessed { _ in conn.cancel() })
    }
    
    // Generic JSON POST handler: parses body, calls handler, returns {success, error} JSON
    private func handleJSONPost(
        _ connection: NWConnection,
        leftover: Data,
        request: String,
        handler: @escaping ([String: Any]) -> (Bool, String?)
    ) {
        let contentLength = self.parseContentLength(from: request)
        self.readPostBody(on: connection, expectedLength: contentLength, initialData: leftover) { [weak self] bodyData in
            guard let bodyData = bodyData,
                  let json = try? JSONSerialization.jsonObject(with: bodyData) as? [String: Any] else {
                let err: [String: Any] = ["success": false, "error": "Invalid JSON"]
                let data = try? JSONSerialization.data(withJSONObject: err, options: [])
                self?.simpleOK(connection, contentType: "application/json", bodyData: data)
                return
            }
            let (success, errorMsg) = handler(json)
            let response: [String: Any] = ["success": success, "error": errorMsg ?? ""]
            let data = try? JSONSerialization.data(withJSONObject: response, options: [])
            self?.simpleOK(connection, contentType: "application/json", bodyData: data)
        }
    }

    private func handlePostRequest(_ connection: NWConnection, contentLength: Int?, initialData: Data?, completion: @escaping (Data?) -> Void) {
        self.readPostBody(on: connection, expectedLength: contentLength, initialData: initialData) { bodyData in
            completion(bodyData)
        }
    }
    
    private func readPostBody(on connection: NWConnection, expectedLength: Int?, initialData: Data?, completion: @escaping (Data?) -> Void) {
        var bodyData = initialData ?? Data()
        
        func readChunk() {
            connection.receive(minimumIncompleteLength: 1, maximumLength: 8192) { data, _, isComplete, error in
                if let data = data {
                    bodyData.append(data)
                }
                
                // If we know expected length, stop when we reach it
                if let expected = expectedLength, expected > 0 {
                    if bodyData.count >= expected {
                        // 只返回指定长度的内容
                        completion(bodyData.subdata(in: 0..<expected))
                        return
                    }
                    // Continue reading until we have enough bytes
                    if error == nil {
                        readChunk()
                    } else {
                        completion(bodyData.isEmpty ? nil : bodyData)
                    }
                } else {
                    // Fallback: stop when connection signals complete or error
                    if isComplete || error != nil {
                        completion(bodyData.isEmpty ? nil : bodyData)
                    } else {
                        readChunk()
                    }
                }
            }
        }
        
        // 如果已经满足预期长度，无需再读
        if let expected = expectedLength, expected > 0, bodyData.count >= expected {
            completion(bodyData.subdata(in: 0..<expected))
        } else {
            readChunk()
        }
    }
    
    private func indexHTML() -> String {
        // Try to read from external HTML template file
        let bundle = Bundle.main
        if let htmlPath = bundle.path(forResource: "index", ofType: "html"),
           let htmlContent = try? String(contentsOfFile: htmlPath) {
            return htmlContent
        }
        
        // Fallback to embedded HTML if file not found
        return """
        <!doctype html>
        <html lang="zh">
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width,initial-scale=1">
            <title>SpaceSelfLog Monitor</title>
            <style>
                body { background:#111; color:#eee; font-family: -apple-system, BlinkMacSystemFont, Helvetica, Arial; margin: 20px; }
                .row { margin: 10px 0; display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
                button { padding:8px 12px; margin-right:8px; background: #333; color: #eee; border: 1px solid #555; border-radius: 4px; cursor: pointer; }
                .video-container { display: flex; justify-content: center; align-items: center; background: #000; width: 600px; height: 600px; margin: 0 auto; overflow: hidden; position: relative; }
                img { max-width: 600px; max-height: 600px; width: auto; height: auto; object-fit: contain; background: #000; }
                .mono { font-family: Menlo, monospace; }
            </style>
        </head>
        <body>
            <h3>SpaceSelfLog</h3>
            <div class="row">
                <div class="video-container">
                    <img src="/stream" alt="stream">
                </div>
            </div>
            <div class="row">
                <button onclick="fetch('/start')">🟢 Start</button>
                <button onclick="fetch('/stop')">🔴 Stop</button>
            </div>
            <div class="row mono" id="status"></div>
            <script>
                async function refresh(){
                    try {
                        const res = await fetch('/status');
                        const j = await res.json();
                        document.getElementById('status').textContent = JSON.stringify(j);
                    } catch(e){ console.log(e) }
                }
                setInterval(refresh, 1500); refresh();
            </script>
        </body>
        </html>
        """
    }
}
