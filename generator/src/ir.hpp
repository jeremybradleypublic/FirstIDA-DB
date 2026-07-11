#pragma once
#include <string>

namespace disasmgen {

enum class Ty { I32, I64, F64 };
enum class BinOp { Add, Sub, Mul };
enum class CmpOp { Lt, Gt, Eq };  // Eq is only ever GENERATED for integer types

// One tiny typed function shape — the single source of truth for BOTH the C
// renderer (render_c.cpp) and the asmjit lowerer (lower_asmjit.cpp), which is
// what guarantees the (asm, source) correspondence by construction:
//
//   T f(T a, T b) {
//       T acc = (T)init_const;                       // typed local
//       for (int i = 0; i < trip_count; ++i) {       // ONE bounded loop
//           acc = acc <loop_op> a;                   // add/sub/mul
//       }
//       if (acc <cmp> b) {                           // ONE comparison
//           acc = acc <post_op> b;
//       }
//       return acc;                                  // a return
//   }
//
// No calls, no pointers, no memory.
struct IRFunc {
  std::string name;
  Ty ty = Ty::I32;
  BinOp loop_op = BinOp::Add;
  BinOp post_op = BinOp::Sub;
  CmpOp cmp = CmpOp::Lt;
  int trip_count = 4;       // 1..16
  long long init_const = 1; // small non-negative constant
};

const char* ty_cname(Ty ty);  // "int" | "long long" | "double"

}  // namespace disasmgen
