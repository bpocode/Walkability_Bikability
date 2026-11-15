// Keep the map iframe in place when a point click updates the chart.
export default function ({ parentElement, data, setTriggerValue }) {
    const frame = parentElement.querySelector("iframe");
    if (frame.dataset.route !== data.route) {
        frame.srcdoc = data.mapHtml;
        frame.dataset.route = data.route;
    }

    function onPointClick(event) {
        if (event.source === frame.contentWindow && event.origin === window.location.origin &&
            event.data?.type === "route-point" && Number.isInteger(event.data.index)) {
            setTriggerValue("point", event.data.index);
        }
    }

    window.addEventListener("message", onPointClick);
    return () => window.removeEventListener("message", onPointClick);
}
