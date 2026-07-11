#pragma once
#include "ir.hpp"
#include <cstdint>
#include <vector>

namespace disasmgen {

// Deterministically draw `count` random IRFuncs. F64 never draws CmpOp::Eq
// (float equality is not lowered); trip_count in [1,16]; init_const in [0,99].
std::vector<IRFunc> synthesize_ir(int count, uint64_t seed);

}  // namespace disasmgen
