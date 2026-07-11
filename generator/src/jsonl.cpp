#include "jsonl.hpp"

#include <cstdio>

namespace disasmgen {

std::string json_escape(const std::string& s) {
  std::string out;
  out.reserve(s.size() + 8);
  for (unsigned char c : s) {
    switch (c) {
      case '"':  out += "\\\""; break;
      case '\\': out += "\\\\"; break;
      case '\n': out += "\\n"; break;
      case '\r': out += "\\r"; break;
      case '\t': out += "\\t"; break;
      default:
        if (c < 0x20) {
          char buf[8];
          std::snprintf(buf, sizeof buf, "\\u%04x", c);
          out += buf;
        } else {
          out += static_cast<char>(c);
        }
    }
  }
  return out;
}

void JsonObj::add(const std::string& key, const std::string& value) {
  parts_.push_back("\"" + json_escape(key) + "\":\"" + json_escape(value) + "\"");
}

void JsonObj::add_int(const std::string& key, long long value) {
  parts_.push_back("\"" + json_escape(key) + "\":" + std::to_string(value));
}

std::string JsonObj::str() const {
  std::string out = "{";
  for (size_t i = 0; i < parts_.size(); ++i) {
    if (i) out += ",";
    out += parts_[i];
  }
  out += "}";
  return out;
}

}  // namespace disasmgen
