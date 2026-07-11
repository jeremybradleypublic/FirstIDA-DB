#pragma once
#include "ir.hpp"
#include <cstdint>
#include <string>
#include <vector>

namespace disasmgen {

// Lower `f` to raw x86-64 machine code (SysV: a = edi/rdi/xmm0,
// b = esi/rsi/xmm1; return in eax/rax/xmm0). Returns the flat byte buffer,
// or an empty vector with *err set on failure (a failed IR is SKIPPED by the
// caller, never fatal to the batch).
std::vector<uint8_t> lower_x64(const IRFunc& f, std::string* err);

}  // namespace disasmgen
