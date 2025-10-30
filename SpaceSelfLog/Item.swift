//
//  Item.swift
//  SpaceSelfLog
//
//  Created by Chris Wu on 10/29/25.
//

import Foundation
import SwiftData

@Model
final class Item {
    var timestamp: Date
    
    init(timestamp: Date) {
        self.timestamp = timestamp
    }
}
