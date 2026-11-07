//! vim model — terminal text editor.

#[derive(Debug, Clone)]
pub struct Document {
    pub id: String,
    pub path: String,
    pub content: String,
    pub modified: bool,
}

#[derive(Debug, Clone)]
pub struct Model {
    pub documents: Vec<Document>,
    pub next_id: u64,
}

impl Default for Model {
    fn default() -> Self { Self { documents: vec![], next_id: 1 } }
}

impl Model {
    pub fn new() -> Self { Self::default() }

    pub fn open(&mut self, path: &str, content: &str) -> String {
        let id = format!("{:x}", self.next_id);
        self.next_id += 1;
        self.documents.push(Document { id: id.clone(), path: path.into(), content: content.into(), modified: false });
        id
    }

    pub fn save(&mut self, id: &str) -> bool {
        if let Some(d) = self.documents.iter_mut().find(|d| d.id == id) {
            d.modified = false;
            true
        } else { false }
    }

    pub fn edit(&mut self, id: &str, content: &str) -> bool {
        if let Some(d) = self.documents.iter_mut().find(|d| d.id == id) {
            d.content = content.into();
            d.modified = true;
            true
        } else { false }
    }

    pub fn list(&self) -> &[Document] { &self.documents }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn document_edit_save() {
        let mut v = Model::new();
        let id = v.open("/tmp/test.txt", "hello");
        assert!(v.edit(&id, "world"));
        assert!(v.save(&id));
    }
}
