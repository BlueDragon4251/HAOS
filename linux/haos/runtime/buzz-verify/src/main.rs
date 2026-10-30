//! Bounded offline Nostr verification through the official, pinned Rust SDK.
use std::io::{self, Read};
use nostr::{Event, JsonUtil};

fn verify() -> Result<(), Box<dyn std::error::Error>> {
    let mut input = Vec::new();
    io::stdin().take(1_048_577).read_to_end(&mut input)?;
    if input.is_empty() || input.len() > 1_048_576 {
        return Err("bounded signed Nostr event required".into());
    }
    let event = Event::from_json(&input)?;
    event.verify()?;
    println!("{}", serde_json::json!({"valid":true,"id":event.id.to_hex(),"pubkey":event.pubkey.to_hex()}));
    Ok(())
}

fn main() {
    if verify().is_err() {
        // Do not echo parser errors, event content, tags or other untrusted data.
        println!("{{\"valid\":false}}");
        std::process::exit(1);
    }
}
