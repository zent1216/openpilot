// 준파일럿 로그 수신기 (구글 Apps Script 웹앱)
// 콤마4가 보낸 주행 기록 조각을 구글 드라이브 "준파일럿 로그" 폴더에 저장한다.
// 큰 파일은 이름.part000, 이름.part001 … 로 나뉘어 저장된다.

const SECRET = '여기에-긴-비밀값-입력';  // 관리 페이지 "연결" 탭의 비밀값과 똑같이
const ROOT_NAME = '준파일럿 로그';

function doPost(e) {
  try {
    const req = JSON.parse(e.postData.contents);
    if (req.secret !== SECRET) return out({ ok: false, error: '비밀값이 맞지 않아요.' });
    if (!/^[\w.\-가-힣]+$/.test(req.bundle) || !/^[\w.\-]+$/.test(req.name)) return out({ ok: false, error: '파일 이름 형식이 올바르지 않아요.' });

    const folder = sub(sub(DriveApp.getRootFolder(), ROOT_NAME), req.bundle);
    const name = req.total > 1 ? `${req.name}.part${String(req.part).padStart(3, '0')}` : req.name;
    const old = folder.getFilesByName(name);
    while (old.hasNext()) old.next().setTrashed(true);  // 재전송 시 덮어쓰기
    folder.createFile(Utilities.newBlob(Utilities.base64Decode(req.data), 'application/octet-stream', name));
    return out({ ok: true });
  } catch (err) {
    return out({ ok: false, error: String(err) });
  }
}

function doGet() {
  return out({ ok: true, app: 'junpilot-receiver' });
}

function sub(parent, name) {
  const it = parent.getFoldersByName(name);
  return it.hasNext() ? it.next() : parent.createFolder(name);
}

function out(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
