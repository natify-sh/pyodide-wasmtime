// BUILD tool (Node + the npm `binaryen` package, as wasm-opt/wasm-merge): turn a libc function of pyodide.asm.wasm
// that is a stub INSIDE the module into an import that the adapter answers.
//
//   node tools/patch_main.mjs BINARYEN_DIR IN.wasm OUT.wasm
//
// `setsockopt` is, in Pyodide's build, libc's stub with the system call inlined as "returns 0" (Emscripten's JavaScript
// has no __syscall_setsockopt), so a program's setsockopt was lost and getsockopt never saw it. Its body becomes
//     r = env.__syscall_setsockopt_host(fd, level, optname, optval, optlen, 0); if (r < 0) { errno = -r; return -1 } return 0
// which the adapter answers with the host's operation. The function keeps its name, its export and its callers.
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

const [dir, input, output] = process.argv.slice(2);
const binaryen = (await import(pathToFileURL(path.resolve(dir, "index.js")).href)).default;
const m = binaryen.readBinary(fs.readFileSync(input));
m.setFeatures(binaryen.Features.All & ~binaryen.Features.CompactImports); // as wasm-opt --all-features --disable-compact-imports

const internal = (name) => {
  const exp = m.getExport(name);
  if (!exp) throw new Error(`${name}: no such export`);
  return binaryen.getExportInfo(exp).value;
};
const i32 = binaryen.i32;
const fname = internal("setsockopt");
const errnoLocation = internal("__errno_location");
const params = binaryen.getFunctionInfo(m.getFunction(fname)).params;
if (binaryen.expandType(params).length !== 5) throw new Error("setsockopt does not take 5 arguments");
m.addFunctionImport("__syscall_setsockopt_host", "env", "__syscall_setsockopt_host", binaryen.createType([i32, i32, i32, i32, i32, i32]), i32);
const arg = (i) => m.local.get(i, i32);
const r = 5; // the first local after the 5 parameters
const body = m.block(null, [
  m.local.set(r, m.call("__syscall_setsockopt_host", [arg(0), arg(1), arg(2), arg(3), arg(4), m.i32.const(0)], i32)),
  m.if(
    m.i32.lt_s(m.local.get(r, i32), m.i32.const(0)),
    m.block(null, [
      m.i32.store(0, 4, m.call(errnoLocation, [], i32), m.i32.sub(m.i32.const(0), m.local.get(r, i32))),
      m.return(m.i32.const(-1)),
    ]),
  ),
  m.i32.const(0),
], i32);
m.removeFunction(fname);
m.addFunction(fname, params, i32, [i32], body);
if (!m.validate()) throw new Error("the patched module is not valid");
fs.writeFileSync(output, m.emitBinary());
