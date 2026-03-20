import Foundation
import UIKit

// MARK: - API Response Models
struct GeminiResponse: Codable {
    let candidates: [GeminiCandidate]
}

struct GeminiCandidate: Codable {
    let content: GeminiContent
}

struct GeminiContent: Codable {
    let parts: [GeminiPart]
}

struct GeminiPart: Codable {
    let text: String
}

// MARK: - API Request Models
struct GeminiRequest: Codable {
    let contents: [GeminiRequestContent]
}

struct GeminiRequestContent: Codable {
    let parts: [GeminiRequestPart]
}

struct GeminiRequestPart: Codable {
    let text: String?
    let inlineData: GeminiInlineData?
    
    init(text: String) {
        self.text = text
        self.inlineData = nil
    }
    
    init(imageData: Data) {
        self.text = nil
        self.inlineData = GeminiInlineData(mimeType: "image/jpeg", data: imageData.base64EncodedString())
    }
}

struct GeminiInlineData: Codable {
    let mimeType: String
    let data: String
}

// MARK: - Gemini API Service
final class GeminiAPIService {
    private let session = URLSession.shared
    private let baseURL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
    
    enum APIError: Error, LocalizedError {
        case invalidURL
        case invalidAPIKey
        case noResponse
        case invalidResponse
        case networkError(Error)
        case apiError(String)
        
        var errorDescription: String? {
            switch self {
            case .invalidURL:
                return "Invalid API URL"
            case .invalidAPIKey:
                return "Invalid API Key"
            case .noResponse:
                return "No response received"
            case .invalidResponse:
                return "Invalid response format"
            case .networkError(let error):
                return "Network error: \(error.localizedDescription)"
            case .apiError(let message):
                return "API error: \(message)"
            }
        }
    }
    
    func analyzeImage(imageData: Data, prompt: String, apiKey: String, completion: @escaping (Result<String, APIError>) -> Void) {
        guard !apiKey.isEmpty else {
            completion(.failure(.invalidAPIKey))
            return
        }
        
        guard let url = URL(string: "\(baseURL)?key=\(apiKey)") else {
            completion(.failure(.invalidURL))
            return
        }
        
        // Build request body
        let request = GeminiRequest(contents: [
            GeminiRequestContent(parts: [
                GeminiRequestPart(text: prompt),
                GeminiRequestPart(imageData: imageData)
            ])
        ])
        
        var urlRequest = URLRequest(url: url)
        urlRequest.httpMethod = "POST"
        urlRequest.setValue("application/json", forHTTPHeaderField: "Content-Type")
        
        do {
            urlRequest.httpBody = try JSONEncoder().encode(request)
        } catch {
            completion(.failure(.networkError(error)))
            return
        }
        
        // Send request
        session.dataTask(with: urlRequest) { data, response, error in
            if let error = error {
                completion(.failure(.networkError(error)))
                return
            }
            
            guard let data = data else {
                completion(.failure(.noResponse))
                return
            }
            
            // Check HTTP status code
            if let httpResponse = response as? HTTPURLResponse {
                if httpResponse.statusCode != 200 {
                    // Try to parse error information
                    if let errorString = String(data: data, encoding: .utf8) {
                        completion(.failure(.apiError("HTTP \(httpResponse.statusCode): \(errorString)")))
                    } else {
                        completion(.failure(.apiError("HTTP \(httpResponse.statusCode)")))
                    }
                    return
                }
            }
            
            // Parse response
            do {
                let geminiResponse = try JSONDecoder().decode(GeminiResponse.self, from: data)
                
                if let firstCandidate = geminiResponse.candidates.first,
                   let firstPart = firstCandidate.content.parts.first {
                    completion(.success(firstPart.text))
                } else {
                    completion(.failure(.invalidResponse))
                }
            } catch {
                // If JSON parsing fails, print raw response for debugging
                if let responseString = String(data: data, encoding: .utf8) {
                    print("GeminiAPIService: Parsing failed, raw response: \(responseString)")
                }
                completion(.failure(.networkError(error)))
            }
        }.resume()
    }
    
    // Test if API Key is valid
    func testAPIKey(_ apiKey: String, completion: @escaping (Result<Void, APIError>) -> Void) {
        // Create a simple test image (1x1 pixel white image)
        let testImageData = createTestImage()
        
        analyzeImage(imageData: testImageData, prompt: "What do you see?", apiKey: apiKey) { result in
            switch result {
            case .success:
                completion(.success(()))
            case .failure(let error):
                completion(.failure(error))
            }
        }
    }
    
    private func createTestImage() -> Data {
        let size = CGSize(width: 1, height: 1)
        UIGraphicsBeginImageContext(size)
        UIColor.white.setFill()
        UIRectFill(CGRect(origin: .zero, size: size))
        let image = UIGraphicsGetImageFromCurrentImageContext()
        UIGraphicsEndImageContext()
        
        return image?.jpegData(compressionQuality: 0.8) ?? Data()
    }
}