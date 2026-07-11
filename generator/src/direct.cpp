#include "direct.hpp"

#include <random>
#include <string>

namespace disasmgen {
namespace {

struct TypeInfo {
  const char* cname;
  const char* abbr;
  bool is_float;
};

constexpr TypeInfo kTypes[] = {
    {"int", "i", false},          {"unsigned int", "u", false},
    {"long", "l", false},         {"float", "f", true},
    {"double", "d", true},
};
constexpr int kNumTypes = 5;
constexpr int kNumFamilies = 6;

using Rng = std::mt19937_64;

int ri(Rng& r, int lo, int hi) {  // uniform int in [lo, hi]
  return static_cast<int>(lo + r() % static_cast<uint64_t>(hi - lo + 1));
}

std::string num(int v) { return std::to_string(v); }

// Family 0: reduction loop over an array.
DirectFunc reduce_loop(Rng& r, const TypeInfo& t, const std::string& name) {
  int k = ri(r, 1, 9), m = ri(r, 2, 7);
  std::string T = t.cname;
  std::string sig = T + " " + name + "(const " + T + " *xs, int n)";
  std::string src = sig + " {\n" +
      "    " + T + " acc = " + num(k) + ";\n" +
      "    for (int i = 0; i < n; ++i) {\n" +
      "        acc += xs[i] * " + num(m) + ";\n" +
      "    }\n" +
      "    return acc;\n}\n";
  return {name, "c", sig, src};
}

// Family 1: dot product of two arrays.
DirectFunc dot_product(Rng& r, const TypeInfo& t, const std::string& name) {
  int stride = ri(r, 1, 3);
  std::string T = t.cname;
  std::string sig = T + " " + name + "(const " + T + " *a, const " + T +
                    " *b, int n)";
  std::string src = sig + " {\n" +
      "    " + T + " s = 0;\n" +
      "    for (int i = 0; i < n; i += " + num(stride) + ") {\n" +
      "        s += a[i] * b[i];\n" +
      "    }\n" +
      "    return s;\n}\n";
  return {name, "c", sig, src};
}

// Family 2: bitwise mixer (always unsigned, regardless of the swept type).
DirectFunc bitmix(Rng& r, const TypeInfo&, const std::string& name) {
  int s1 = ri(r, 1, 15), s2 = ri(r, 1, 15);
  unsigned mask = 0x0f0f0f0fu << ri(r, 0, 3);
  std::string sig = "unsigned int " + name + "(unsigned int a, unsigned int b)";
  std::string src = sig + " {\n" +
      "    unsigned int x = a ^ (b << " + num(s1) + ");\n" +
      "    x |= (a >> " + num(s2) + ");\n" +
      "    return x & " + std::to_string(mask) + "u;\n}\n";
  return {name, "c", sig, src};
}

// Family 3: branchy compare chain returning small codes.
DirectFunc branchy(Rng& r, const TypeInfo& t, const std::string& name) {
  int t1 = ri(r, 1, 40), t2 = t1 + ri(r, 1, 40);
  std::string T = t.cname;
  std::string sig = "int " + name + "(" + T + " x, " + T + " y)";
  std::string src = sig + " {\n" +
      "    if (x < " + num(t1) + ") {\n" +
      "        return y > x ? 1 : 2;\n" +
      "    }\n" +
      "    if (x < " + num(t2) + ") {\n" +
      "        return y == x ? 3 : 4;\n" +
      "    }\n" +
      "    return 5;\n}\n";
  return {name, "c", sig, src};
}

// Family 4: small string op — count occurrences of one character.
DirectFunc count_char(Rng& r, const TypeInfo&, const std::string& name) {
  char ch = static_cast<char>('a' + ri(r, 0, 25));
  std::string sig = "int " + name + "(const char *s)";
  std::string src = sig + " {\n" +
      "    int c = 0;\n" +
      "    while (*s) {\n" +
      "        if (*s == '" + std::string(1, ch) + "') {\n" +
      "            ++c;\n" +
      "        }\n" +
      "        ++s;\n" +
      "    }\n" +
      "    return c;\n}\n";
  return {name, "c", sig, src};
}

// Family 5: C++ reference-parameter saturating accumulate.
DirectFunc ref_accumulate(Rng& r, const TypeInfo& t, const std::string& name) {
  int cap = ri(r, 50, 500);
  std::string T = t.cname;
  std::string sig = T + " " + name + "(" + T + " &acc, " + T + " v)";
  std::string src = sig + " {\n" +
      "    acc += v;\n" +
      "    if (acc > " + num(cap) + ") {\n" +
      "        acc = " + num(cap) + ";\n" +
      "    }\n" +
      "    return acc;\n}\n";
  return {name, "cpp", sig, src};
}

const char* kFamilyTag[kNumFamilies] = {"red", "dot", "bit", "brc", "cnt", "acc"};

}  // namespace

std::vector<DirectFunc> synthesize_direct(int count, uint64_t seed) {
  Rng r(seed ^ 0x9e3779b97f4a7c15ull);
  std::vector<DirectFunc> out;
  out.reserve(count);
  for (int idx = 0; idx < count; ++idx) {
    const TypeInfo& t = kTypes[r() % kNumTypes];
    int fam = static_cast<int>(r() % kNumFamilies);
    std::string name = std::string("g_") + kFamilyTag[fam] + "_" + t.abbr +
                       "_" + std::to_string(idx);
    switch (fam) {
      case 0: out.push_back(reduce_loop(r, t, name)); break;
      case 1: out.push_back(dot_product(r, t, name)); break;
      case 2: out.push_back(bitmix(r, t, name)); break;
      case 3: out.push_back(branchy(r, t, name)); break;
      case 4: out.push_back(count_char(r, t, name)); break;
      default: out.push_back(ref_accumulate(r, t, name)); break;
    }
  }
  return out;
}

}  // namespace disasmgen
