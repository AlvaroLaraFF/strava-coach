import { useEffect, useRef } from "react";
import L from "leaflet";

// Plain Leaflet (BSD-2) drawn via refs — deliberately NOT react-leaflet
// (Hippocratic License). Draws the route polyline from the latlng stream.
export default function SessionMap({ latlng }: { latlng: [number, number][] }) {
  const ref = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);

  useEffect(() => {
    if (!ref.current || !latlng.length) return;
    const pts = latlng.filter((p) => Array.isArray(p) && p.length === 2) as [number, number][];
    if (!pts.length) return;

    const map = L.map(ref.current, { zoomControl: true, attributionControl: true });
    mapRef.current = map;
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: "© OpenStreetMap", maxZoom: 19,
    }).addTo(map);

    const line = L.polyline(pts, { color: "#fc5200", weight: 4, opacity: 0.9 }).addTo(map);
    L.circleMarker(pts[0], { radius: 6, color: "#4ade80", fillOpacity: 1 }).addTo(map).bindTooltip("Inicio");
    L.circleMarker(pts[pts.length - 1], { radius: 6, color: "#f87171", fillOpacity: 1 }).addTo(map).bindTooltip("Fin");
    map.fitBounds(line.getBounds(), { padding: [24, 24] });

    return () => { map.remove(); mapRef.current = null; };
  }, [latlng]);

  if (!latlng.length) return null;
  return <div className="map" ref={ref} />;
}
