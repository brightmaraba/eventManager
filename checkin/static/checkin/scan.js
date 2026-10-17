(function () {
  var start = document.getElementById("scan-start");
  var video = document.getElementById("scan-video");
  var status = document.getElementById("scan-status");
  var form = document.getElementById("scan-form");
  var tokenInput = document.getElementById("scan-token");
  if (!start || !video || !form || !tokenInput) {
    return;
  }

  function tokenFrom(value) {
    var match = String(value || "").match(/\/checkin\/t\/([^/?#]+)/);
    if (match) {
      return decodeURIComponent(match[1]);
    }
    return String(value || "").trim();
  }

  function submitToken(raw) {
    var token = tokenFrom(raw);
    if (!token) {
      return;
    }
    tokenInput.value = token;
    form.submit();
  }

  start.addEventListener("click", function () {
    if (!navigator.mediaDevices || !window.BarcodeDetector) {
      status.textContent = "This browser cannot scan from the camera. Paste the code instead.";
      return;
    }
    navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } }).then(function (stream) {
      video.srcObject = stream;
      return video.play();
    }).then(function () {
      status.textContent = "Point the camera at the ticket QR.";
      var detector = new BarcodeDetector({ formats: ["qr_code"] });
      var stopped = false;

      function scanFrame() {
        if (stopped) {
          return;
        }
        detector.detect(video).then(function (codes) {
          if (stopped) {
            return;
          }
          if (codes.length && codes[0].rawValue) {
            stopped = true;
            var stream = video.srcObject;
            if (stream) {
              stream.getTracks().forEach(function (track) { track.stop(); });
            }
            submitToken(codes[0].rawValue);
            return;
          }
          window.requestAnimationFrame(scanFrame);
        }).catch(function () {
          if (!stopped) {
            window.requestAnimationFrame(scanFrame);
          }
        });
      }

      window.requestAnimationFrame(scanFrame);
    }).catch(function () {
      status.textContent = "The camera is unavailable. Paste the code instead.";
    });
  });
})();
