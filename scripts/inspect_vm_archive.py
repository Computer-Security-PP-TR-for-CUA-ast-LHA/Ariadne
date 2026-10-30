"""Read only the official ZIP central directory before full download completes."""
import io
import json
import urllib.request
import zipfile

class Remote(io.RawIOBase):
    size = 12126194516
    pos = 0

    def seekable(self):
        return True

    def seek(self, offset, whence=0):
        self.pos = offset + (self.pos if whence == 1 else self.size if whence == 2 else 0)
        return self.pos

    def tell(self):
        return self.pos

    def read(self, size=-1):
        size = min(self.size-self.pos, size if size >= 0 else self.size-self.pos)
        if size <= 0:
            return b""
        start, end = self.pos, self.pos + size - 1
        req = urllib.request.Request("https://huggingface.co/datasets/xlangai/ubuntu_osworld/resolve/main/Ubuntu-x86.zip",
                                     headers={"Range": f"bytes={start}-{end}"})
        with urllib.request.urlopen(req, timeout=30) as response:
            if response.headers.get("Content-Range") != f"bytes {start}-{end}/{self.size}":
                raise RuntimeError("Incorrect range")
            data = response.read()
        self.pos += len(data)
        return data

with zipfile.ZipFile(Remote()) as archive:
    print(json.dumps({"members": len(archive.infolist()), "expanded_bytes": sum(x.file_size for x in archive.infolist()),
                      "configs": [x.filename for x in archive.infolist() if x.filename.endswith((".vmx", ".vmsd", ".vmss"))]}))
    for name in archive.namelist():
        if name.endswith((".vmx", ".vmsd")):
            content = archive.read(name).decode("utf-8", errors="replace")
            print(name)
            print("\n".join(line for line in content.splitlines() if any(word in line.lower() for word in
                ("memsize", "numvcpus", "displayname", "snapshot", "ethernet0.connectiontype", "guestos"))))
