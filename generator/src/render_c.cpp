#include "render_c.hpp"

namespace disasmgen {
namespace {

const char* op_c(BinOp op) {
  switch (op) {
    case BinOp::Add: return "+";
    case BinOp::Sub: return "-";
    default:         return "*";
  }
}

const char* cmp_c(CmpOp c) {
  switch (c) {
    case CmpOp::Lt: return "<";
    case CmpOp::Gt: return ">";
    default:        return "==";
  }
}

}  // namespace

const char* ty_cname(Ty ty) {
  switch (ty) {
    case Ty::I32: return "int";
    case Ty::I64: return "long long";
    default:      return "double";
  }
}

std::string signature_of(const IRFunc& f) {
  std::string t = ty_cname(f.ty);
  return t + " " + f.name + "(" + t + " a, " + t + " b)";
}

std::string render_c(const IRFunc& f) {
  std::string t = ty_cname(f.ty);
  std::string s = signature_of(f) + " {\n";
  s += "    " + t + " acc = " + std::to_string(f.init_const);
  if (f.ty == Ty::F64) s += ".0";
  s += ";\n";
  s += "    for (int i = 0; i < " + std::to_string(f.trip_count) + "; ++i) {\n";
  s += std::string("        acc = acc ") + op_c(f.loop_op) + " a;\n";
  s += "    }\n";
  s += std::string("    if (acc ") + cmp_c(f.cmp) + " b) {\n";
  s += std::string("        acc = acc ") + op_c(f.post_op) + " b;\n";
  s += "    }\n";
  s += "    return acc;\n}\n";
  return s;
}

}  // namespace disasmgen
