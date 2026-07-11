#include "../src/format_zydis.hpp"
#include "../src/hybrid.hpp"
#include "../src/ir.hpp"
#include "../src/lower_asmjit.hpp"

#include <cstdio>
#include <sstream>
#include <string>
#include <vector>

#define CHECK(cond)                                                          \
  do {                                                                       \
    if (!(cond)) {                                                           \
      std::fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond);   \
      return 1;                                                              \
    }                                                                        \
  } while (0)

// Pull the mnemonic (first token after "<offset>: ") out of each asm line.
static std::vector<std::string> mnemonics(const std::string& asm_text) {
  std::vector<std::string> out;
  std::istringstream ss(asm_text);
  std::string line;
  while (std::getline(ss, line)) {
    size_t colon = line.find(": ");
    if (colon == std::string::npos) continue;
    std::string rest = line.substr(colon + 2);
    size_t sp = rest.find(' ');
    out.push_back(sp == std::string::npos ? rest : rest.substr(0, sp));
  }
  return out;
}

int main() {
  using namespace disasmgen;

  // (1) Fixed IR -> bytes -> zydis -> known mnemonic sequence.
  IRFunc f;
  f.name = "fixture";
  f.ty = Ty::I32;
  f.loop_op = BinOp::Add;
  f.post_op = BinOp::Sub;
  f.cmp = CmpOp::Lt;
  f.trip_count = 4;
  f.init_const = 1;

  std::string err;
  std::vector<uint8_t> bytes = lower_x64(f, &err);
  CHECK(!bytes.empty());
  std::string text = format_asm(bytes, &err);
  CHECK(!text.empty());
  std::vector<std::string> m = mnemonics(text);
  // NOTE: asmjit emits the signed JGE opcode (0x7D); Zydis's Intel formatter
  // spells that instruction "jnl" (jump-if-not-less) — same instruction.
  const char* want[] = {"mov", "mov", "add", "dec", "jnz",
                        "cmp", "jnl", "sub", "ret"};
  CHECK(m.size() == 9);
  for (int i = 0; i < 9; ++i) CHECK(m[i] == want[i]);

  // (2) F64 path returns via xmm0 and compares with ucomisd.
  f.ty = Ty::F64;
  f.loop_op = BinOp::Mul;
  f.cmp = CmpOp::Gt;
  bytes = lower_x64(f, &err);
  CHECK(!bytes.empty());
  text = format_asm(bytes, &err);
  CHECK(text.find("ucomisd") != std::string::npos);
  CHECK(text.find("mulsd") != std::string::npos);

  // (3) Eq on F64 is a structured skip, not a crash.
  f.cmp = CmpOp::Eq;
  err.clear();
  CHECK(lower_x64(f, &err).empty());
  CHECK(!err.empty());

  // (4) Every IR in a seeded batch lowers and decodes cleanly, and the
  //     synthesizer never draws Eq for F64.
  for (const auto& ir : synthesize_ir(25, 7)) {
    if (ir.ty == Ty::F64) CHECK(ir.cmp != CmpOp::Eq);
    CHECK(ir.trip_count >= 1 && ir.trip_count <= 16);
    std::string e;
    std::vector<uint8_t> b = lower_x64(ir, &e);
    CHECK(!b.empty());
    CHECK(!format_asm(b, &e).empty());
  }
  // determinism
  CHECK(synthesize_ir(25, 7)[3].name == synthesize_ir(25, 7)[3].name);
  CHECK(synthesize_ir(25, 7)[3].trip_count == synthesize_ir(25, 7)[3].trip_count);
  std::puts("ok test_hybrid");
  return 0;
}
