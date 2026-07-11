#pragma once
#include <cstdint>
#include <string>
#include <vector>

namespace disasmgen {

// Decode raw x86-64 bytes into Intel-syntax text, one instruction per line,
// formatted "<hex offset>: <instruction>". Returns "" with *err set if any
// byte fails to decode (caller SKIPS the record; never fatal to the batch).
std::string format_asm(const std::vector<uint8_t>& bytes, std::string* err);

}  // namespace disasmgen
