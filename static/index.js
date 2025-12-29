// https://en.wikipedia.org/wiki/Unicode_character_property#General_Category
// valid username characters: letters, number digits, number letters,
//                            punctuation connectors, punctuation dashes
const username_re = /[^\p{L}\p{Nd}\p{Nl}\p{Pc}\p{Pd}\p{Zs}]/u;
// time to wait before checking API for username availibility
// avoids unnecessary requests for partially typed values
const debounce_ms = 200;
// request_controller cancels earlier API requests if a new one is made
let request_controller = null, previous_username = null;
function apijson(response) {
  if (!response.ok) {
    return Promise.reject(response)
  }
  return response.json()
}

let distinctive = "347ADEFHLMNQRdefmr";
function generateShortID(size=8, chars=distinctive) {
  // console.info(1 / 2 + Math.sqrt(1 / 4 + 2 * Math.log(2) * Math.pow(
  //     chars.length, size)))
  res = ""
  for (let i = 0; i < size; i++) {
    res += chars[Math.trunc(Math.random() * chars.length)]
  }
  return res
}

function check_username() {
  const el = document.getElementById("username");
  const input = el.value;
  const output = document.getElementById("username-status");
  const submit = document.getElementById("submit");
  // avoids checking on key up for the shift key, for example
  if (input === previous_username) return;
  previous_username = input;
  let invalid;
  if (input === "") {
    output.innerText = "";
    submit.disabled = true;
  } else if (input.length > 512) {
    output.innerText = "Too long";
    submit.disabled = true;
  } else if (invalid = input.match(username_re)) {
    // specify "whitespace" for invisible error specifics
    const char_type = invalid[0].match(/\p{Zs}/u) ? "whitespace " : "";
    output.innerText = `Invalid ${char_type}character "${invalid[0]}"`;
    submit.disabled = true;
  } else {
    output.innerText = "";
    submit.disabled = false;
    return
    if (request_controller !== null) {
      request_controller.abort();
    }
    request_controller = new AbortController();
    const signal = request_controller.signal;
    setTimeout(() => {
      if (signal.aborted) return;
      output.innerText = "checking availability...";
      const query = encodeURIComponent(input);
      request = fetch(`api/username-available?v=${query}`, { signal })
        .then(apijson).then((data) => {
          if (data) {
            output.innerText = "";
            submit.disabled = false;
          } else {
            output.innerText = "Username not available";
            submit.disabled = true;
          }
        }).catch((error) => {
          if (!signal.aborted) {
            output.innerText = "Couldn't reach the server";
          }
        });
    }, debounce_ms);
  }
}

function claim_username() {
  const storage = document.getElementById("storage");
  if (!storage.checked) {
    window.alert(
        "audio data has to be stored until there's a reliable GPU source " +
        "behind the project")
    storage.checked = true;
    storage.previousSibling.textContent =
        "I agree to the terms and conditions";
    return
  }
  const el = document.getElementById("username")
  const input = el.value;
  const output = document.getElementById("username-status");
  const submit = document.getElementById("submit");
  if (request_controller !== null) {
    request_controller.abort();
  }
  request_controller = new AbortController();
  const signal = request_controller.signal;
  submit.disabled = true;
  let url = URL.parse("api/set-username", window.location.href)
  url.searchParams.set("v", input)
  let project = document.getElementById("project").value
  url.searchParams.set("project", project)
  url.searchParams.set("list", document.getElementById("list").value)
  url.searchParams.set(
    "t", document.querySelector("[name=test-type]:checked").id)
  request = fetch(url, { signal })
    .then(apijson).then((data) => {
      if (data) {
        // window.location.href = "pitch.html";
        project = project === "null" ? data : project
        window.location.href = `${project}.html`;
        submit.disabled = false;
      } else {
        output.innerText = "Username not available";
      }
    }).catch((error) => {
      if (!signal.aborted) {
        output.innerText = "Couldn't reach the server";
        submit.disabled = false;
      }
    })
}

fetch("api/lists", {method: "POST"}).then(apijson).then(data => {
  let parent = document.getElementById("project");
  Object.keys(data).forEach(x => {
    if (x === "") return;
    let el = parent.appendChild(document.createElement("option"));
    el.setAttribute("value", x);
    el.innerText = x;
  })
  let secondary = document.getElementById("list");
  function updated() {
    let project = parent.value === "null" ? data[""] : parent.value
    while (secondary.firstElementChild)
      secondary.removeChild(secondary.firstElementChild)
    let el = secondary.appendChild(document.createElement("option"));
    el.setAttribute("value", null);
    el.innerText = "Default";
    data[project].forEach(x => {
      let el = secondary.appendChild(document.createElement("option"));
      el.setAttribute("value", x);
      el.innerText = x;
    })
    document.getElementById("results").href =
      `recognized.html?user=all&project=${project}`
  }
  updated()
  parent.addEventListener("change", updated)
}).catch(e => {
  if (e.status === 401) {
    window.location.href = "/login?next=" + encodeURIComponent(
      window.location.href)
  }
})

class TestRecorder extends DiscretelyTunedRecorder {
    debug(message) {
        let container = document.getElementById("mic-debug")
        container.innerText = message
    }
}

let recorder
window.addEventListener("load", () => {
  let samples = document.getElementById("samples")
  for (const el of document.getElementsByClassName("playback-interface")) {
    const src = el.getAttribute("data-src")
    if (src === null) continue
    let audio = document.createElement("audio")
    audio.addEventListener("canplaythrough", ((el, audio) => () => {
      el.classList.remove("load")
      el.classList.add("play")
      let playing = false
      const f = (actively) => () => {
        playing = !playing
        el.classList.remove("play")
        el.classList.remove("pause")
        el.classList.add(playing ? "pause" : "play")
        if (!actively) audio.load()
        else if (playing) audio.play()
        else audio.pause()
      }
      el.addEventListener("click", f(true))
      audio.addEventListener("ended", f(false))
    })(el, audio))
    audio.src = src
    audio.setAttribute("preload", "")
    samples.appendChild(audio)
  }
  // Only recorder if microphone test element exists so that review page doesn't trigger request
  const soundDots = document.querySelectorAll(".sound-dot");
  if (soundDots.length > 0) {
    recorder = new TestRecorder(".sound-dot")
  }
  check_username()
})

