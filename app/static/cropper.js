// Square image cropper for the logo uploads on /admin/board.
// Markup: <form data-cropper> with input[type=file], canvas, input[type=range], input[name=image].
// Drag to move, slider (or mouse wheel) to zoom; on submit the visible square is
// exported as a 256x256 PNG data URL into the hidden "image" field.
(function () {
  "use strict";
  var OUT = 256;

  function setup(form) {
    var file = form.querySelector("input[type=file]");
    var canvas = form.querySelector("canvas");
    var zoom = form.querySelector("input[type=range]");
    var hidden = form.querySelector("input[name=image]");
    var save = form.querySelector("button[type=submit]");
    var ctx = canvas.getContext("2d");
    var size = canvas.width;  // square viewport
    var img = null, scale = 1, minScale = 1, x = 0, y = 0;  // image top-left in canvas pixels
    var drag = null;

    function clamp() {  // keep the square covered by the image
      var w = img.width * scale, h = img.height * scale;
      x = Math.min(0, Math.max(size - w, x));
      y = Math.min(0, Math.max(size - h, y));
    }

    function draw() {
      ctx.clearRect(0, 0, size, size);
      if (!img) return;
      ctx.drawImage(img, x, y, img.width * scale, img.height * scale);
    }

    function setScale(next, cx, cy) {  // zoom around a point in the viewport
      next = Math.max(minScale, Math.min(minScale * 8, next));
      x = cx - (cx - x) * next / scale;
      y = cy - (cy - y) * next / scale;
      scale = next;
      clamp();
      draw();
    }

    file.addEventListener("change", function () {
      var f = file.files && file.files[0];
      if (!f) return;
      var reader = new FileReader();
      reader.onload = function () {
        var i = new Image();
        i.onload = function () {
          img = i;
          minScale = scale = size / Math.min(i.width, i.height);  // "cover" the square
          x = (size - i.width * scale) / 2;
          y = (size - i.height * scale) / 2;
          zoom.value = 1;
          zoom.disabled = false;
          save.disabled = false;
          draw();
        };
        i.src = reader.result;
      };
      reader.readAsDataURL(f);
    });

    zoom.addEventListener("input", function () {
      if (img) setScale(minScale * parseFloat(zoom.value), size / 2, size / 2);
    });

    canvas.addEventListener("wheel", function (e) {
      if (!img) return;
      e.preventDefault();
      var r = canvas.getBoundingClientRect(), k = size / r.width;
      setScale(scale * (e.deltaY < 0 ? 1.1 : 1 / 1.1), (e.clientX - r.left) * k, (e.clientY - r.top) * k);
      zoom.value = scale / minScale;
    }, { passive: false });

    canvas.addEventListener("pointerdown", function (e) {
      if (!img) return;
      canvas.setPointerCapture(e.pointerId);
      drag = { px: e.clientX, py: e.clientY, x: x, y: y };
    });
    canvas.addEventListener("pointermove", function (e) {
      if (!drag) return;
      var k = size / canvas.getBoundingClientRect().width;  // CSS px -> canvas px
      x = drag.x + (e.clientX - drag.px) * k;
      y = drag.y + (e.clientY - drag.py) * k;
      clamp();
      draw();
    });
    function stop() { drag = null; }
    canvas.addEventListener("pointerup", stop);
    canvas.addEventListener("pointercancel", stop);

    form.addEventListener("submit", function (e) {
      if (e.submitter && e.submitter.hasAttribute("formaction")) return;  // "Use placeholder"
      if (!img) { e.preventDefault(); return; }
      var out = document.createElement("canvas");
      out.width = out.height = OUT;
      var k = OUT / size;
      out.getContext("2d").drawImage(img, x * k, y * k, img.width * scale * k, img.height * scale * k);
      hidden.value = out.toDataURL("image/png");
    });
  }

  document.querySelectorAll("form[data-cropper]").forEach(setup);
})();
