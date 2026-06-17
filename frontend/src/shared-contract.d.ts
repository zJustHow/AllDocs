/// <reference types="vite/client" />

declare module "@shared/markers.json" {
  const value: {
    regex: {
      inlineCitationRef: string;
      inlineCitationMarker: string;
      embedMarker: string;
      embedMarkerLoose: string;
      messageToken: string;
    };
    embed: {
      markerTemplate: string;
      bboxRoundDecimals: number;
    };
  };
  export default value;
}

declare module "@shared/file_formats.json" {
  const value: {
    types: Array<{
      extension: string;
      contentType: string;
      label: string;
      previewMode: "pdf" | "image" | "text" | "unsupported";
    }>;
  };
  export default value;
}
