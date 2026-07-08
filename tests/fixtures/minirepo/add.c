#include "add.h"
int add(int a, int b) { return a + b; }
static int mul(int a, int b) { return a * b; }
int use(int x) { return add(x, mul(x, 2)); }
