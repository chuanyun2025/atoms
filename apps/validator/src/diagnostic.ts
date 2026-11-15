type Location = {file?:string; line?:number; column?:number; subject?:string; occurrences?:number};

export class ValidationDiagnostic extends Error {
  constructor(readonly code:string, message:string, readonly location:Location = {}) {
    const {file,line,column} = location;
    super(file && line ? `${file}:${line}:${column ?? 1} ${message}` : message);
  }

  response() {
    const {file,subject,...coordinates}=this.location;
    return {ok:false,error:this.message.slice(0,2000),diagnostic:{
      code:this.code,file:file?.slice(0,400),subject:subject?.slice(0,400),...coordinates,
    }};
  }
}
