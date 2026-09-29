// Read-only evidence extraction. Never recalculate, edit, or export the workbook.
import fs from 'node:fs/promises';
import {FileBlob, SpreadsheetFile} from '@oai/artifact-tool';

const [inputPath, outputPath] = process.argv.slice(2);
const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(inputPath));
const summary = await workbook.inspect({kind:'sheet', include:'id,name', maxChars:4000});
const ranges = [];
for (const [name, address] of [
  ['使用说明','A5:C16'], ['案例目录','A5:J12'], ['官方文献数值','A5:J24'],
  ['原始资源','A5:H20'], ['运行对照','A5:L23'],
]) {
  const range = workbook.worksheets.getItem(name).getRange(address);
  ranges.push({sheet:name, range:address, values:range.values, formulas:range.formulas});
}
await fs.writeFile(outputPath, JSON.stringify({
  method:'@oai/artifact-tool importXlsx + inspect + bounded values/formulas getters',
  modified:false, recalculated:false, exported:false, summary:summary.ndjson, ranges,
}, null, 2) + '\n');
