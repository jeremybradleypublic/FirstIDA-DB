# x86-64 ELF toolchain: GCC, Clang, and binutils (objdump, c++filt).
FROM --platform=linux/amd64 debian:bookworm-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      gcc g++ clang binutils libc6-dev \
 && rm -rf /var/lib/apt/lists/*
CMD ["sleep", "infinity"]
