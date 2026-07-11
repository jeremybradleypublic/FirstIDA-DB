#include "direct.hpp"
#include "format_zydis.hpp"
#include "hybrid.hpp"
#include "jsonl.hpp"
#include "lower_asmjit.hpp"
#include "render_c.hpp"

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

namespace {

void usage() {
  std::fprintf(stderr,
               "usage: disasmgen <direct|hybrid> [--count N] [--seed S] "
               "[--out PATH]\n");
}

struct Args {
  std::string route;
  int count = 100;
  unsigned long long seed = 0;
  std::string out_path;  // empty -> stdout
};

bool parse_args(int argc, char** argv, Args* a) {
  if (argc < 2) return false;
  a->route = argv[1];
  if (a->route != "direct" && a->route != "hybrid") return false;
  for (int i = 2; i < argc; ++i) {
    std::string flag = argv[i];
    if (i + 1 >= argc) return false;
    const char* val = argv[++i];
    if (flag == "--count")     a->count = std::atoi(val);
    else if (flag == "--seed") a->seed = std::strtoull(val, nullptr, 10);
    else if (flag == "--out")  a->out_path = val;
    else return false;
  }
  return a->count > 0;
}

}  // namespace

int main(int argc, char** argv) {
  Args args;
  if (!parse_args(argc, argv, &args)) {
    usage();
    return 2;
  }

  std::FILE* out = stdout;
  if (!args.out_path.empty()) {
    out = std::fopen(args.out_path.c_str(), "w");
    if (!out) {  // unrecoverable setup failure -> non-zero exit
      std::fprintf(stderr, "{\"error\":\"cannot open out path %s\"}\n",
                   disasmgen::json_escape(args.out_path).c_str());
      return 1;
    }
  }

  int emitted = 0, skipped = 0;
  if (args.route == "direct") {
    for (const auto& f : disasmgen::synthesize_direct(
             args.count, static_cast<uint64_t>(args.seed))) {
      disasmgen::JsonObj o;
      o.add("route", "direct");
      o.add("func_name", f.func_name);
      o.add("lang", f.lang);
      o.add("signature", f.signature);
      o.add("source_text", f.source_text);
      o.add_int("seed", static_cast<long long>(args.seed));
      std::fprintf(out, "%s\n", o.str().c_str());
      ++emitted;
    }
  } else {
    for (const auto& ir : disasmgen::synthesize_ir(
             args.count, static_cast<uint64_t>(args.seed))) {
      std::string err;
      std::vector<uint8_t> bytes = disasmgen::lower_x64(ir, &err);
      std::string asm_text =
          bytes.empty() ? std::string() : disasmgen::format_asm(bytes, &err);
      if (asm_text.empty()) {  // structured skip on stderr; never abort batch
        std::fprintf(stderr, "{\"skip\":\"%s\",\"reason\":\"%s\"}\n",
                     disasmgen::json_escape(ir.name).c_str(),
                     disasmgen::json_escape(err).c_str());
        ++skipped;
        continue;
      }
      disasmgen::JsonObj o;
      o.add("route", "hybrid");
      o.add("func_name", ir.name);
      o.add("lang", "c");
      o.add("signature", disasmgen::signature_of(ir));
      o.add("source_text", disasmgen::render_c(ir));
      o.add_int("seed", static_cast<long long>(args.seed));
      o.add("asm_text", asm_text);
      o.add("obj_format", "rawx86_64");
      o.add("compiler", "asmjit");
      o.add("opt_level", "none");
      std::fprintf(out, "%s\n", o.str().c_str());
      ++emitted;
    }
  }
  if (out != stdout) std::fclose(out);
  std::fprintf(stderr,
               "{\"done\":true,\"route\":\"%s\",\"emitted\":%d,\"skipped\":%d}\n",
               args.route.c_str(), emitted, skipped);
  return 0;
}
