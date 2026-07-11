#include "lower_asmjit.hpp"

#include <asmjit/x86.h>

namespace disasmgen {
namespace {

using namespace asmjit;

void emit_int_op(x86::Assembler& a, BinOp op, const x86::Gp& dst,
                 const x86::Gp& src) {
  switch (op) {
    case BinOp::Add: a.add(dst, src); break;
    case BinOp::Sub: a.sub(dst, src); break;
    case BinOp::Mul: a.imul(dst, src); break;
  }
}

void emit_f64_op(x86::Assembler& a, BinOp op, const x86::Vec& dst,
                 const x86::Vec& src) {
  switch (op) {
    case BinOp::Add: a.addsd(dst, src); break;
    case BinOp::Sub: a.subsd(dst, src); break;
    case BinOp::Mul: a.mulsd(dst, src); break;
  }
}

}  // namespace

std::vector<uint8_t> lower_x64(const IRFunc& f, std::string* err) {
  Environment env;
  env.set_arch(Arch::kX64);
  CodeHolder code;
  if (code.init(env) != Error::kOk) {
    if (err) *err = "asmjit CodeHolder init failed";
    return {};
  }
  x86::Assembler a(&code);

  Label loop = a.new_label();
  Label skip = a.new_label();

  if (f.ty == Ty::F64) {
    // acc = xmm2; a = xmm0, b = xmm1 (SysV float args); return in xmm0.
    if (f.cmp == CmpOp::Eq) {  // never generated for F64; guard anyway
      if (err) *err = "Eq comparison unsupported for F64";
      return {};
    }
    a.mov(x86::eax, static_cast<int>(f.init_const));
    a.cvtsi2sd(x86::xmm2, x86::eax);        // acc = (double)init_const
    a.mov(x86::ecx, f.trip_count);
    a.bind(loop);
    emit_f64_op(a, f.loop_op, x86::xmm2, x86::xmm0);
    a.dec(x86::ecx);
    a.jnz(loop);
    a.ucomisd(x86::xmm2, x86::xmm1);
    if (f.cmp == CmpOp::Lt) a.jae(skip);    // !(acc < b)
    else                    a.jbe(skip);    // !(acc > b)
    emit_f64_op(a, f.post_op, x86::xmm2, x86::xmm1);
    a.bind(skip);
    a.movapd(x86::xmm0, x86::xmm2);
    a.ret();
  } else {
    // acc = eax/rax; a = edi/rdi, b = esi/rsi; return in eax/rax.
    auto emit_int_body = [&](const x86::Gp& acc, const x86::Gp& pa,
                             const x86::Gp& pb) {
      a.mov(acc, f.init_const);
      a.mov(x86::ecx, f.trip_count);
      a.bind(loop);
      emit_int_op(a, f.loop_op, acc, pa);
      a.dec(x86::ecx);
      a.jnz(loop);
      a.cmp(acc, pb);
      if (f.cmp == CmpOp::Lt)      a.jge(skip);  // signed !(acc < b)
      else if (f.cmp == CmpOp::Gt) a.jle(skip);  // signed !(acc > b)
      else                         a.jne(skip);  // !(acc == b)
      emit_int_op(a, f.post_op, acc, pb);
      a.bind(skip);
      a.ret();
    };
    if (f.ty == Ty::I64) emit_int_body(x86::rax, x86::rdi, x86::rsi);
    else                 emit_int_body(x86::eax, x86::edi, x86::esi);
  }

  if (code.flatten() != Error::kOk || code.has_unresolved_fixups()) {
    if (err) *err = "asmjit produced unresolved code";
    return {};
  }
  const CodeBuffer& buf = code.text_section()->buffer();
  return std::vector<uint8_t>(buf.data(), buf.data() + buf.size());
}

}  // namespace disasmgen
