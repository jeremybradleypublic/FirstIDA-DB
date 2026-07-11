#include "format_zydis.hpp"

#include <Zydis/Zydis.h>

#include <cstdio>

namespace disasmgen {

std::string format_asm(const std::vector<uint8_t>& bytes, std::string* err) {
  ZydisDecoder decoder;
  if (!ZYAN_SUCCESS(ZydisDecoderInit(&decoder, ZYDIS_MACHINE_MODE_LONG_64,
                                     ZYDIS_STACK_WIDTH_64))) {
    if (err) *err = "zydis decoder init failed";
    return "";
  }
  ZydisFormatter formatter;
  if (!ZYAN_SUCCESS(ZydisFormatterInit(&formatter, ZYDIS_FORMATTER_STYLE_INTEL))) {
    if (err) *err = "zydis formatter init failed";
    return "";
  }

  std::string out;
  ZyanUSize offset = 0;
  ZydisDecodedInstruction insn;
  ZydisDecodedOperand operands[ZYDIS_MAX_OPERAND_COUNT];
  while (offset < bytes.size()) {
    if (!ZYAN_SUCCESS(ZydisDecoderDecodeFull(&decoder, bytes.data() + offset,
                                             bytes.size() - offset, &insn,
                                             operands))) {
      if (err) *err = "undecodable byte at offset " + std::to_string(offset);
      return "";
    }
    char text[256];
    if (!ZYAN_SUCCESS(ZydisFormatterFormatInstruction(
            &formatter, &insn, operands, insn.operand_count_visible, text,
            sizeof text, offset, ZYAN_NULL))) {
      if (err) *err = "format failed at offset " + std::to_string(offset);
      return "";
    }
    char line[300];
    std::snprintf(line, sizeof line, "%4llx: %s\n",
                  static_cast<unsigned long long>(offset), text);
    out += line;
    offset += insn.length;
  }
  return out;
}

}  // namespace disasmgen
