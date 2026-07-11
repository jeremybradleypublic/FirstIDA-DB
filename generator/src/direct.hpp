#pragma once
#include <cstdint>
#include <string>
#include <vector>

namespace disasmgen {

struct DirectFunc {
  std::string func_name;
  std::string lang;         // "c" | "cpp"
  std::string signature;
  std::string source_text;  // one complete, self-contained function definition
};

// Deterministically synthesize `count` diverse self-contained functions from
// parameterized templates swept over element types and shape knobs.
std::vector<DirectFunc> synthesize_direct(int count, uint64_t seed);

}  // namespace disasmgen
