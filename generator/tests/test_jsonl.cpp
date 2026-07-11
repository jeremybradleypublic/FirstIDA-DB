#include "../src/jsonl.hpp"
#include <cstdio>
#include <string>

#define CHECK(cond)                                                          \
  do {                                                                       \
    if (!(cond)) {                                                           \
      std::fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond);   \
      return 1;                                                              \
    }                                                                        \
  } while (0)

int main() {
  using disasmgen::json_escape;
  CHECK(json_escape("plain") == "plain");
  CHECK(json_escape("a\"b") == "a\\\"b");
  CHECK(json_escape("line1\nline2") == "line1\\nline2");
  CHECK(json_escape("back\\slash") == "back\\\\slash");
  CHECK(json_escape("tab\there") == "tab\\there");
  CHECK(json_escape(std::string("nul\x01" "byte")) == "nul\\u0001byte");

  disasmgen::JsonObj o;
  o.add("func_name", "f\"1");
  o.add("source_text", "int f(void) {\n  return 1;\n}");
  o.add_int("seed", 42);
  CHECK(o.str() ==
        "{\"func_name\":\"f\\\"1\","
        "\"source_text\":\"int f(void) {\\n  return 1;\\n}\","
        "\"seed\":42}");
  std::puts("ok test_jsonl");
  return 0;
}
