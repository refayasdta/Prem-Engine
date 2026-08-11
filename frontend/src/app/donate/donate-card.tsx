"use client";

import { useState } from "react";
import styles from "./donate.module.css";

const ACCOUNT_NUMBER = "4972090712";

type CopyStatus = "idle" | "copied" | "error";

function copyWithTemporaryField(value: string) {
  const field = document.createElement("textarea");
  field.value = value;
  field.setAttribute("readonly", "");
  field.style.position = "fixed";
  field.style.opacity = "0";
  document.body.appendChild(field);
  field.select();
  const copied = document.execCommand("copy");
  document.body.removeChild(field);
  return copied;
}

export function DonateCard() {
  const [status, setStatus] = useState<CopyStatus>("idle");

  async function copyAccountNumber() {
    setStatus("idle");

    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(ACCOUNT_NUMBER);
        setStatus("copied");
        return;
      }

      setStatus(copyWithTemporaryField(ACCOUNT_NUMBER) ? "copied" : "error");
    } catch {
      try {
        setStatus(copyWithTemporaryField(ACCOUNT_NUMBER) ? "copied" : "error");
      } catch {
        setStatus("error");
      }
    }
  }

  return (
    <div className={styles.cardArea}>
      <button
        className={styles.bankCard}
        type="button"
        onClick={copyAccountNumber}
        data-status={status}
        aria-label={`Copy BCA account number ${ACCOUNT_NUMBER}`}
        aria-describedby="donation-copy-status"
      >
        <span className={styles.bankName}>BCA</span>
        <span className={styles.accountHolder}>a.n Azaria Refaya Siddharta</span>
        <strong className={styles.accountNumber}>{ACCOUNT_NUMBER}</strong>
        <span className={styles.copyPrompt}>
          {status === "copied" ? "Account number copied" : "Click to copy"}
        </span>
      </button>

      <p
        className={styles.statusMessage}
        id="donation-copy-status"
        role={status === "error" ? "alert" : "status"}
        aria-live="polite"
      >
        {status === "copied"
          ? `BCA account number ${ACCOUNT_NUMBER} copied to your clipboard.`
          : status === "error"
            ? "The account number could not be copied. Please select it manually."
            : ""}
      </p>

      <div
        className={`${styles.thankYou} ${status === "copied" ? styles.thankYouVisible : ""}`}
        aria-hidden={status !== "copied"}
      >
        Thank you for supporting Prem Engine.
      </div>
    </div>
  );
}
