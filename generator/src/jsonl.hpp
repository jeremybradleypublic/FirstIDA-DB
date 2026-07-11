#pragma once
#include <string>
#include <vector>

namespace disasmgen {

// Escape a string for embedding inside a JSON string literal:
// quotes, backslashes, \n \r \t, and all other control chars as \u00XX.
std::string json_escape(const std::string& s);

// Builds one single-line JSON object: {"k":"v","n":42}. Insertion order is
// preserved. This is the ONLY JSON emitter in the generator — no JSON lib.
class JsonObj {
 public:
  void add(const std::string& key, const std::string& value);
  void add_int(const std::string& key, long long value);
  std::string str() const;

 private:
  std::vector<std::string> parts_;
};

}  // namespace disasmgen
