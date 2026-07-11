#pragma once
#include "ir.hpp"
#include <string>

namespace disasmgen {

// "int f(int a, int b)"
std::string signature_of(const IRFunc& f);

// The complete C function definition implementing the IR semantics.
std::string render_c(const IRFunc& f);

}  // namespace disasmgen
