#include "../src/ir.hpp"
#include "../src/render_c.hpp"
#include <cstdio>
#include <string>

#define CHECK(cond)                                                          \
  do {                                                                       \
    if (!(cond)) {                                                           \
      std::fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond);   \
      return 1;                                                              \
    }                                                                        \
  } while (0)

static bool has(const std::string& hay, const char* needle) {
  return hay.find(needle) != std::string::npos;
}

int main() {
  using namespace disasmgen;
  IRFunc f;
  f.name = "fixture";
  f.ty = Ty::I32;
  f.loop_op = BinOp::Add;
  f.post_op = BinOp::Sub;
  f.cmp = CmpOp::Lt;
  f.trip_count = 4;
  f.init_const = 1;

  CHECK(std::string(ty_cname(Ty::I32)) == "int");
  CHECK(std::string(ty_cname(Ty::I64)) == "long long");
  CHECK(std::string(ty_cname(Ty::F64)) == "double");
  CHECK(signature_of(f) == "int fixture(int a, int b)");

  std::string src = render_c(f);
  CHECK(has(src, "int fixture(int a, int b) {"));
  CHECK(has(src, "int acc = 1;"));
  CHECK(has(src, "for (int i = 0; i < 4; ++i) {"));
  CHECK(has(src, "acc = acc + a;"));
  CHECK(has(src, "if (acc < b) {"));
  CHECK(has(src, "acc = acc - b;"));
  CHECK(has(src, "return acc;"));

  f.ty = Ty::F64;
  f.loop_op = BinOp::Mul;
  f.cmp = CmpOp::Gt;
  std::string fsrc = render_c(f);
  CHECK(has(fsrc, "double fixture(double a, double b) {"));
  CHECK(has(fsrc, "double acc = 1.0;"));
  CHECK(has(fsrc, "acc = acc * a;"));
  CHECK(has(fsrc, "if (acc > b) {"));
  std::puts("ok test_render_c");
  return 0;
}
