#include "../src/direct.hpp"
#include <cstdio>
#include <set>
#include <string>

#define CHECK(cond)                                                          \
  do {                                                                       \
    if (!(cond)) {                                                           \
      std::fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond);   \
      return 1;                                                              \
    }                                                                        \
  } while (0)

int main() {
  auto funcs = disasmgen::synthesize_direct(60, 42);
  CHECK(funcs.size() == 60);
  std::set<std::string> names;
  bool saw_c = false, saw_cpp = false;
  for (const auto& f : funcs) {
    CHECK(!f.source_text.empty());
    CHECK(f.source_text.find(f.func_name) != std::string::npos);
    CHECK(!f.signature.empty());
    CHECK(f.signature.find(f.func_name) != std::string::npos);
    CHECK(f.lang == "c" || f.lang == "cpp");
    saw_c = saw_c || f.lang == "c";
    saw_cpp = saw_cpp || f.lang == "cpp";
    CHECK(names.insert(f.func_name).second);  // unique in batch
  }
  CHECK(saw_c);
  CHECK(saw_cpp);
  // deterministic per seed
  auto again = disasmgen::synthesize_direct(60, 42);
  CHECK(again[7].source_text == funcs[7].source_text);
  // a different seed changes at least one shape knob somewhere
  auto other = disasmgen::synthesize_direct(60, 43);
  bool differs = false;
  for (size_t i = 0; i < 60; ++i) {
    if (other[i].source_text != funcs[i].source_text) { differs = true; break; }
  }
  CHECK(differs);
  std::puts("ok test_direct");
  return 0;
}
