#include "hybrid.hpp"

#include <random>

namespace disasmgen {

std::vector<IRFunc> synthesize_ir(int count, uint64_t seed) {
  std::mt19937_64 r(seed ^ 0xda3e39cb94b95bdbull);
  std::vector<IRFunc> out;
  out.reserve(count);
  for (int i = 0; i < count; ++i) {
    IRFunc f;
    f.ty = static_cast<Ty>(r() % 3);
    f.loop_op = static_cast<BinOp>(r() % 3);
    f.post_op = static_cast<BinOp>(r() % 3);
    f.cmp = (f.ty == Ty::F64) ? static_cast<CmpOp>(r() % 2)   // Lt | Gt only
                              : static_cast<CmpOp>(r() % 3);  // Lt | Gt | Eq
    f.trip_count = static_cast<int>(1 + r() % 16);
    f.init_const = static_cast<long long>(r() % 100);
    const char* ts = (f.ty == Ty::I32) ? "i32"
                     : (f.ty == Ty::I64) ? "i64" : "f64";
    f.name = std::string("h_") + ts + "_" + std::to_string(i);
    out.push_back(f);
  }
  return out;
}

}  // namespace disasmgen
