import {defineConfig} from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig({
  plugins:[react()],
  server:{host:"0.0.0.0",port:5173,strictPort:true,allowedHosts:["localhost","127.0.0.1","web"],watch:{usePolling:true},hmr:{clientPort:Number(process.env.HMR_CLIENT_PORT||8080)}},
  build:{sourcemap:false}
});
