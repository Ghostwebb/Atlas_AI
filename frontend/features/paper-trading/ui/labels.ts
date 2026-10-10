/** Spanish labels for the paper trading screen. Pure data; no behavior. */
import type { ControllerError, Phase } from "../controller";
import type { BrokerStatus, Proposal, Reservation, SubmissionStatus } from "../types";
import type { Availability } from "./account";

export const PHASE_LABEL: Record<Phase, string> = {
  idle: "Sin operación",
  recovering: "Recuperando la operación de esta pestaña…",
  preparing: "Preparando propuesta…",
  review: "Propuesta lista para revisar",
  confirming: "Enviando confirmación…",
  uncertain: "Resultado incierto",
  tracking: "Siguiendo la orden",
  final: "Operación finalizada",
  expired: "Propuesta vencida",
};

export const PROPOSAL_STATUS_LABEL: Record<Proposal["status"], string> = {
  open: "Abierta (sin enviar)", confirmed: "Confirmada", expired: "Vencida",
};

export const SUBMISSION_LABEL: Record<SubmissionStatus, string> = {
  not_submitted: "No enviada",
  submitting: "Enviándose (lease activa)",
  submitted: "Enviada a Alpaca Paper",
  submission_unknown: "Incierto: puede haberse enviado",
  rejected_by_broker: "Rechazada por Alpaca Paper",
  failed_before_submit: "No llegó a Alpaca (se puede confirmar de nuevo)",
};

export const BROKER_LABEL: Record<BrokerStatus, string> = {
  new: "Nueva", accepted: "Aceptada", pending_new: "Pendiente de alta", accepted_for_bidding: "Aceptada para subasta",
  partially_filled: "Ejecutada parcialmente", filled: "Ejecutada", done_for_day: "Terminada por hoy",
  canceled: "Cancelada", expired: "Expirada", replaced: "Reemplazada", pending_cancel: "Cancelación pendiente",
  pending_replace: "Reemplazo pendiente", stopped: "Detenida", rejected: "Rechazada", suspended: "Suspendida",
  calculated: "Calculada", unrecognized: "Desconocido",
};

export const RESERVATION_LABEL: Record<Reservation["state"], string> = {
  held: "Retenida (pendiente de acuse)", acknowledged: "Activa en Alpaca", released: "Liberada",
};

export const AVAILABILITY: Record<Availability, { label: string; detail: string }> = {
  loading: { label: "Comprobando…", detail: "Consultando el backend de ATLAS." },
  unreachable: { label: "Inaccesible", detail: "No hay respuesta del backend de ATLAS. Comprueba que está en marcha." },
  disabled: { label: "Deshabilitada", detail: "Paper Trading está desactivado en el servidor (ATLAS_PAPER_TRADING_ENABLED)." },
  not_configured: { label: "Sin configurar", detail: "Faltan las claves de Alpaca Paper en el entorno del backend." },
  broker_unreachable: { label: "Alpaca Paper inaccesible", detail: "El backend no puede contactar con Alpaca Paper ahora mismo." },
  available: { label: "Disponible", detail: "Conectado al backend de ATLAS con una cuenta Alpaca Paper." },
};

/** Human message for an error. The technical detail (code, message, correlationId) is shown apart. */
export function errorMessage(error: ControllerError, side: "buy" | "sell" | null): string {
  switch (error.code) {
    case "PAPER_DISABLED": return "Paper Trading está deshabilitado en el servidor.";
    case "PAPER_NOT_CONFIGURED": return "Faltan las claves de Alpaca Paper en el backend.";
    case "BROKER_UNAVAILABLE": return "Alpaca Paper no responde ahora mismo. Inténtalo más tarde.";
    case "MARKET_CLOSED": return "El mercado regular está cerrado. La orden no se envió.";
    case "RESOURCE_RESERVED": return side === "sell"
      ? "Hay acciones comprometidas por otra orden pendiente."
      : "Hay presupuesto reservado por una operación pendiente.";
    case "RECONCILIATION_REQUIRED": return "Debes consultar el estado antes de intentar otra operación.";
    case "PROPOSAL_EXPIRED": return "La propuesta venció. Prepara una nueva.";
    case "BROKER_REJECTED": return "Alpaca Paper rechazó la orden.";
    case "SUBMISSION_UNCERTAIN": return "El resultado del envío es incierto. Consulta el estado; la orden no se reenviará.";
    case "SUBMISSION_IN_PROGRESS": return "La orden se está enviando. Espera y consulta el estado.";
    case "NETWORK_ERROR": return "No hubo respuesta del backend. Si estabas confirmando, no repitas: consulta el estado.";
    case "ABORTED": return "La petición se interrumpió. Consulta el estado antes de repetir nada.";
    case "INVALID_RESPONSE": return "El backend devolvió datos inválidos o de otra operación. Las acciones quedan bloqueadas hasta una lectura coherente.";
    case "JOURNAL_UNAVAILABLE": return "No se pudo guardar el registro de seguridad en esta pestaña (almacenamiento del navegador). Por seguridad no se envió nada.";
    case "INVALID_INPUT": return "Revisa los datos: símbolo y un importe o cantidad decimal (por ejemplo 100.00).";
    case "INVALID_REQUEST": return "El backend rechazó los datos de la solicitud.";
    case "INSUFFICIENT_BUYING_POWER": return "No hay poder de compra suficiente en la cuenta paper.";
    case "INSUFFICIENT_POSITION": return "No hay suficientes acciones disponibles en la posición.";
    case "ORDER_LIMIT_EXCEEDED": return "El importe supera el límite por orden configurado.";
    case "ASSET_NOT_SUPPORTED": return "Este símbolo no se puede operar en Alpaca Paper.";
    case "FRACTIONAL_NOT_SUPPORTED": return "Este activo no admite fracciones.";
    case "ACCOUNT_NOT_TRADABLE": return "La cuenta paper no puede operar ahora mismo.";
    case "ORDER_NOT_CANCELABLE": return "La orden ya no se puede cancelar (puede haberse ejecutado).";
    case "ORDER_NOT_FOUND": case "PROPOSAL_NOT_FOUND": return "No se encontró la operación en el backend.";
    case "ORIGIN_NOT_ALLOWED": return "El backend no acepta peticiones desde este origen (ATLAS_CORS_ORIGINS).";
    default: return error.message || "Error inesperado.";
  }
}
