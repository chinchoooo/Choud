import { describe, expect, it } from "vitest";

import { fromDrop, fromPickedFolder, groupByDir } from "../src/lib/folderUpload";

function picked(name: string, relative: string): File {
  const file = new File(["x"], name);
  Object.defineProperty(file, "webkitRelativePath", { value: relative });
  return file;
}

describe("picked folders", () => {
  it("turns relative paths into folder paths", () => {
    const tree = fromPickedFolder([
      picked("a.txt", "Trip/a.txt"),
      picked("b.txt", "Trip/Day 1/b.txt"),
      picked("c.txt", ""),
    ]);
    expect(tree.map((t) => t.dir)).toEqual(["Trip", "Trip/Day 1", ""]);
  });

  it("groups files by folder so each folder is made once", () => {
    const groups = groupByDir(fromPickedFolder([picked("a", "T/a"), picked("b", "T/b"), picked("c", "T/S/c")]));
    expect([...groups.keys()]).toEqual(["T", "T/S"]);
    expect(groups.get("T")).toHaveLength(2);
  });
});

describe("dropped folders", () => {
  const fileEntry = (name: string) => ({
    isFile: true,
    isDirectory: false,
    name,
    file: (ok: (f: File) => void) => ok(new File(["x"], name)),
  });
  const dirEntry = (name: string, children: unknown[]) => {
    let served = false;
    return {
      isFile: false,
      isDirectory: true,
      name,
      createReader: () => ({
        readEntries: (ok: (entries: unknown[]) => void) => {
          ok(served ? [] : children);
          served = true;
        },
      }),
    };
  };
  const items = (entries: unknown[]) =>
    entries.map((entry) => ({ webkitGetAsEntry: () => entry })) as unknown as DataTransferItemList;

  it("walks nested folders and keeps their structure", async () => {
    const tree = await fromDrop(
      items([dirEntry("Trip", [fileEntry("a.txt"), dirEntry("Day 1", [fileEntry("b.txt")])]), fileEntry("loose.txt")]),
    );
    expect(tree.map((t) => `${t.dir}|${t.file.name}`).sort()).toEqual(["Trip/Day 1|b.txt", "Trip|a.txt", "|loose.txt"]);
  });

  it("stops at the limit instead of reading a huge tree", async () => {
    const many = Array.from({ length: 20 }, (_, i) => fileEntry(`f${i}`));
    const tree = await fromDrop(items([dirEntry("Big", many)]), 5);
    expect(tree).toHaveLength(5);
  });
});
